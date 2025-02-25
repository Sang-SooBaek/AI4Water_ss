
import json
import math
from typing import Union, Tuple, List

from SeqMetrics import RegressionMetrics, ClassificationMetrics

from ai4water.backend import tf, os, np, pd, plt, easy_mpl
from ai4water.hyperopt import HyperOpt
from ai4water.preprocessing import DataSet
from ai4water.utils.utils import jsonize, ERROR_LABELS
from ai4water.postprocessing import ProcessResults 
from ai4water.utils.utils import clear_weights, dateandtime_now, dict_to_file

plot = easy_mpl.plot
bar_chart = easy_mpl.bar_chart
taylor_plot = easy_mpl.taylor_plot
dumbbell_plot = easy_mpl.dumbbell_plot


if tf is not None:
    if 230 <= int(''.join(tf.__version__.split('.')[0:2]).ljust(3, '0')) < 250:
        from ai4water.functional import Model
        print(f"""
        Switching to functional API due to tensorflow version {tf.__version__} 
        for experiments""")
    else:
        from ai4water import Model
else:
    from ai4water import Model

SEP = os.sep

# todo plots comparing different models in following youtube videos at 6:30 and 8:00 minutes.
# https://www.youtube.com/watch?v=QrJlj0VCHys
# compare models using statistical tests wuch as Giacomini-White test or Diebold-Mariano test
# paired ttest 5x2cv


# in order to unify the use of metrics
Metrics = {
    'regression': lambda t, p, multiclass=False, **kwargs: RegressionMetrics(t, p, **kwargs),
    'classification': lambda t, p, multiclass=False, **kwargs: ClassificationMetrics(t, p, 
        multiclass=multiclass, **kwargs)
}

Monitor = {
    'regression': ['r2', 'corr_coeff', 'mse', 'rmse', 'r2_score',
                'nse', 'kge', 'mape', 'pbias', 'bias', 'mae', 'nrmse',
                'mase'],

    'classification': ['accuracy', 'precision', 'recall', 'mse']
}

class Experiments(object):
    """
    Base class for all the experiments.

    All the expriments must be subclasses of this class.
    The core idea of ``Experiments`` is based upon ``model``. An experiment 
    consists of one or more models. The models differ from each other in their 
    structure/idea/concept/configuration. When :py:meth:`ai4water.experiments.Experiments.fit` 
    is called, each ``model`` is built and trained. The user can customize, building 
    and training process by subclassing this class and customizing 
    :py:meth:`ai4water.experiments.Experiments._build` and 
    :py:meth:`ai4water.experiments.Experiments._fit` methods.

    Attributes
    ------------
    - metrics
    - exp_path
    - model_
    - models

    Methods
    --------
    - fit
    - taylor_plot
    - loss_comparison
    - plot_convergence
    - from_config
    - compare_errors
    - plot_improvement
    - compare_convergence
    - plot_cv_scores
    - fit_with_tpot

    """
    def __init__(
            self,
            cases: dict = None,
            exp_name: str = None,
            num_samples: int = 5,
            verbosity: int = 1,
            monitor: Union[str, list] = None,
    ):
        """

        Arguments
        ---------
            cases :
                python dictionary defining different cases/scenarios
            exp_name :
                name of experiment, used to define path in which results are saved
            num_samples :
                only relevent when you wan to optimize hyperparameters of models
                using ``grid`` method
            verbosity : bool, optional
                determines the amount of information
            monitor : str, list, optional
                list of performance metrics to monitor. It can be any performance
                metric `SeqMetrics_ <https://seqmetrics.readthedocs.io>` library.
                By default ``r2``, ``corr_coeff, ``mse``, ``rmse``, ``r2_score``,
                ``nse``, ``kge``, ``mape``, ``pbias``, ``bias`` ``mae``, ``nrmse``
                ``mase`` are considered for regression and ``accuracy``, ``precision``
                ``recall`` are considered for classification.
        """
        self.opt_results = None
        self.optimizer = None
        self.exp_name = 'Experiments_' + str(dateandtime_now()) if exp_name is None else exp_name
        self.num_samples = num_samples
        self.verbosity = verbosity

        self.models = [method for method in dir(self) if callable(getattr(self, method)) if method.startswith('model_')]

        if cases is None:
            cases = {}
        self.cases = {'model_'+key if not key.startswith('model_') else key: val for key, val in cases.items()}
        self.models = self.models + list(self.cases.keys())

        self.exp_path = os.path.join(os.getcwd(), "results", self.exp_name)
        if not os.path.exists(self.exp_path):
            os.makedirs(self.exp_path)

        self.update_config(models=self.models, exp_path=self.exp_path,
            exp_name=self.exp_name, cases=self.cases)

        if monitor is None:
            self.monitor = Monitor[self.mode]

    def update_and_save_config(self, **kwargs):
        self.update_config(**kwargs)
        self.save_config()
        return

    def update_config(self, **kwargs):
        if not hasattr(self, 'config'):
            setattr(self, 'config', {})
        self.config.update(kwargs.copy())
        return

    def save_config(self):
        dict_to_file(self.exp_path, config=self.config)
        return

    def build_from_config(self, data, config_path, weights, **kwargs):
        setattr(self, 'model_', None)
        raise NotImplementedError

    @property
    def tpot_estimator(self):
        raise NotImplementedError

    @property
    def mode(self):
        raise NotImplementedError

    @property
    def num_samples(self):
        return self._num_samples

    @num_samples.setter
    def num_samples(self, x):
        self._num_samples = x

    def _reset(self):

        self.cv_scores_ = {}

        self.config['eval_models'] = {}
        self.config['optimized_models'] = {}

        self.metrics = {}
        self.features = {}
        self.iter_metrics = {}

        return

    def fit(
            self,
            data,
            run_type: str = "dry_run",
            opt_method: str = "bayes",
            num_iterations: int = 12,
            include: Union[None, list] = None,
            exclude: Union[None, list, str] = '',
            cross_validate: bool = False,
            post_optimize: str = 'eval_best',
            hpo_kws: dict = None
    ):
        """
        Runs the fit loop for all the ``models`` of experiment. The user can
        however, specify the models by making use of ``include`` and ``exclud``
        keywords.

        todo, post_optimize not working for 'eval_best' with ML methods.

        Arguments:
            data: this will be passed to :py:meth:`ai4water.Model.fit`.
            run_type :
                One of ``dry_run`` or ``optimize``. If ``dry_run``, the all
                the `models` will be trained only once. if ``optimize``, then
                hyperparameters of all the models will be optimized.
            opt_method :
                which optimization method to use. options are ``bayes``,
                ``random``, ``grid``. Only valid if ``run_type`` is ``optimize``
            num_iterations : number of iterations for optimization. Only valid
                if ``run_type`` is ``optimize``.
            include :
                name of models to included. If None, all the models found
                will be trained and or optimized.
            exclude :
                name of ``models`` to be excluded
            cross_validate :
                whether to cross validate the model or not. This
                depends upon `cross_validator` agrument to the `Model`.
            post_optimize :
                one of ``eval_best`` or ``train_best``. If eval_best,
                the weights from the best models will be uploaded again and the model
                will be evaluated on train, test and all the data. If ``train_best``,
                then a new model will be built and trained using the parameters of
                the best model.
            hpo_kws :
                keyword arguments for :py:class:`ai4water.hyperopt.HyperOpt` class.

        Examples
        ---------
        >>> from ai4water.experiments import MLRegressionExperiments
        >>> from ai4water.datasets import busan_beach
        >>> exp = MLRegressionExperiments()
        >>> exp.fit(data=busan_beach())

        If you want to compare only RandomForest, XGBRegressor, CatBoostRegressor
        and LGBMRegressor, use the ``include`` keyword

        >>> exp.fit(data=busan_beach(), include=['RandomForestRegressor', 'XGBRegressor',
        >>>    'CatBoostRegressor', 'LGBMRegressor'])

        Similarly, if you want to exclude certain models from comparison, you can
        use ``exclude`` keyword

        >>> exp.fit(data=busan_beach(), exclude=["SGDRegressor"])

        if you want to perform cross validation for each model, we must give
        the ``cross_validator`` argument which will be passed to ai4water Model

        >>> exp = MLRegressionExperiments(cross_validator={"KFold": {"n_splits": 10}})
        >>> exp.fit(data=busan_beach(), cross_validate=True)

        Setting ``cross_validate`` to True will populate `cv_scores_` dictionary
        which can be accessed as ``exp.cv_scores_``

        if you want to optimize the hyperparameters of each model,

        >>> exp.fit(data=busan_beach(), run_type="optimize", num_iterations=20)

        """
        assert run_type in ['optimize', 'dry_run']

        assert post_optimize in ['eval_best', 'train_best']

        if exclude == '':
            exclude = []

        predict = False
        if run_type == 'dry_run':
            predict = True

        if hpo_kws is None:
            hpo_kws = {}

        include = self._check_include_arg(include)

        if exclude is None:
            exclude = []
        elif isinstance(exclude, str):
            exclude = [exclude]

        consider_exclude(exclude, self.models, include)

        self._reset()

        for model_type in include:

            model_name = model_type.split('model_')[1]

            if model_type not in exclude:

                self.model_iter_metric = {}
                self.iter_ = 0

                def objective_fn(**suggested_paras):
                    # the config must contain the suggested parameters by the hpo algorithm
                    if model_type in self.cases:
                        config = self.cases[model_type]
                        config.update(suggested_paras)
                    elif model_name in self.cases:
                        config = self.cases[model_name]
                        config.update(suggested_paras)
                    elif hasattr(self, model_type):
                        config = getattr(self, model_type)(**suggested_paras)
                    else:
                        raise TypeError

                    return self._build_and_run(
                        data=data,
                        predict=predict,
                        cross_validate=cross_validate,
                        title=f"{self.exp_name}{SEP}{model_name}",
                        **config)

                if run_type == 'dry_run':
                    if self.verbosity >= 0: print(f"running  {model_type} model")
                    train_results, test_results = objective_fn()
                    self._populate_results(model_name, train_results, test_results)
                else:
                    # there may be attributes int the model, which needs to be loaded so run the method first.
                    # such as param_space etc.
                    if hasattr(self, model_type):
                        getattr(self, model_type)()

                    opt_dir = os.path.join(os.getcwd(),
                        f"results{SEP}{self.exp_name}{SEP}{model_name}")

                    if self.verbosity > 0: 
                        print(f"optimizing  {model_type} using {opt_method} method")

                    self.optimizer = HyperOpt(
                        opt_method,
                        objective_fn=objective_fn,
                        param_space=self.param_space, 
                        opt_path=opt_dir,
                        num_iterations=num_iterations,  # number of iterations
                        x0=self.x0,
                        verbosity=self.verbosity,
                        **hpo_kws
                        )

                    self.opt_results = self.optimizer.fit()

                    self.config['optimized_models'][model_type] = self.optimizer.opt_path

                    if post_optimize == 'eval_best':
                        self.eval_best(data, model_name, opt_dir)
                    elif post_optimize == 'train_best':
                        self.train_best(data, model_name)

                if not hasattr(self, 'model_'):  # todo asking user to define this parameter is not good
                    raise ValueError(f'The `build` method must set a class level attribute named `model_`.')
                self.config['eval_models'][model_type] = self.model_.path

                if cross_validate:
                    cv_scoring = self.model_.val_metric
                    self.cv_scores_[model_type] = getattr(self.model_, f'cross_val_{cv_scoring}')
                    setattr(self, '_cv_scoring', cv_scoring)

                self.iter_metrics[model_type] = self.model_iter_metric

        self.save_config()

        save_json_file(os.path.join(self.exp_path, 'features.json'), self.features)
        save_json_file(os.path.join(self.exp_path, 'metrics.json'), self.metrics)

        return

    def eval_best(self, data, model_type, opt_dir, **kwargs):
        """Evaluate the best models."""
        best_models = clear_weights(opt_dir, rename=False, write=False)
        # TODO for ML, best_models is empty
        if len(best_models) < 1:
            return self.train_best(data, model_type)
        for mod, props in best_models.items():
            mod_path = os.path.join(props['path'], "config.json")
            mod_weights = props['weights']

            train_results, test_results = self.build_from_config(
                data,
                mod_path, 
                mod_weights, 
                **kwargs)

            if mod.startswith('1_'):
                self._populate_results(model_type, train_results, test_results)
        return

    def train_best(self, data, model_type):
        """Train the best model."""
        best_paras = self.optimizer.best_paras()
        if best_paras.get('lookback', 1) > 1:
            _model = 'layers'
        else:
            _model = model_type
        train_results, test_results = self._build_and_run(
            data=data,
            predict=True,
            model={_model: self.optimizer.best_paras()},
            title=f"{self.exp_name}{SEP}{model_type}{SEP}best"
            )

        self._populate_results(model_type, train_results, test_results)
        return

    def _populate_results(self, model_type: str,
                          train_results: Tuple[np.ndarray, np.ndarray],
                          test_results: Tuple[np.ndarray, np.ndarray]
                          ):

        if not model_type.startswith('model_'):  # internally we always use model_ at the start.
            model_type = f'model_{model_type}'

        # save standard deviation on true and predicted arrays of train and test
        self.features[model_type] = {
            'train': {
                'true': {
                    'std': np.std(train_results[0])},
                'simulation':{
                    'std': np.std(train_results[1])}},

            'test': {
                'true': {
                    'std': np.std(test_results[0])},
                'simulation': {
                    'std': np.std(test_results[1])}}}

        # save performance metrics of train and test
        metrics = Metrics[self.mode](train_results[0],
                                     train_results[1],
                                     multiclass=self.model_.is_multiclass)
        train_metrics = {}
        for metric in self.monitor:
            train_metrics[metric] = getattr(metrics, metric)()

        metrics = Metrics[self.mode](test_results[0],
                                     test_results[1],
                                     multiclass=self.model_.is_multiclass)
        test_metrics = {}
        for metric in self.monitor:
            test_metrics[metric] = getattr(metrics, metric)()

        self.metrics[model_type] = {'train': train_metrics,
                                    'test': test_metrics}
        return

    def taylor_plot(
            self,
            include: Union[None, list] = None,
            exclude: Union[None, list] = None,
            figsize: tuple = (9, 7),
            **kwargs
    )->plt.Figure:
        """
        Compares the models using taylor_plot_.

        Parameters
        ----------
            include : str, list, optional
                if not None, must be a list of models which will be included.
                None will result in plotting all the models.
            exclude : str, list, optional
                if not None, must be a list of models which will excluded.
                None will result in no exclusion
            figsize : tuple, optional
            **kwargs :
                all the keyword arguments for taylor_plot_ function.

        Returns
        -------
        plt.Figure

        Example
        -------
        >>> from ai4water.experiments import MLRegressionExperiments
        >>> from ai4water.datasets import busan_beach
        >>> data = busan_beach()
        >>> inputs = list(data.columns)[0:-1]
        >>> outputs = list(data.columns)[-1]
        >>> experiment = MLRegressionExperiments(input_features=inputs, output_features=outputs)
        >>> experiment.fit(data=data)
        >>> experiment.taylor_plot()

        .. _taylor_plot:
            https://easy-mpl.readthedocs.io/en/latest/plots.html#easy_mpl.taylor_plot
        """
        metrics = self.metrics.copy()

        include = self._check_include_arg(include)

        if exclude is not None:
            consider_exclude(exclude, self.models, metrics)

        if 'name' in kwargs:
            fname = kwargs.pop('name')
        else:
            fname = 'taylor'
        fname = os.path.join(os.getcwd(), f'results{SEP}{self.exp_name}{SEP}{fname}.png')

        train_std = [_model['train']['true']['std'] for _model in self.features.values()]
        train_std = list(set(train_std))[0]
        test_std = [_model['test']['true']['std'] for _model in self.features.values()]
        test_std = list(set(test_std))[0]

        observations = {'train': {'std': train_std},
                        'test': {'std': test_std}}

        simulations = {'train': None, 'test': None}

        for scen in ['train', 'test']:

            scen_stats = {}
            for model, _metrics in metrics.items():
                model_stats = {'std': self.features[model][scen]['simulation']['std'],
                               'corr_coeff': _metrics[scen]['corr_coeff'],
                               'pbias': _metrics[scen]['pbias']
                               }

                if model in include:
                    key = shred_model_name(model)
                    scen_stats[key] = model_stats

            simulations[scen] = scen_stats

        return taylor_plot(
            observations=observations,
            simulations=simulations,
            figsize=figsize,
            name=fname,
            **kwargs
        )

    def _consider_include(self, include: Union[str, list], to_filter):

        filtered = {}

        include = self._check_include_arg(include)

        for m in include:
            if m in to_filter:
                filtered[m] = to_filter[m]

        return filtered

    def _check_include_arg(self, include):

        if isinstance(include, str):
            include = [include]

        if include is None:
            include = self.models
        include = ['model_' + _model if not _model.startswith('model_') else _model for _model in include]

        # make sure that include contains same elements which are present in models
        for elem in include:
            assert elem in self.models, f"""
{elem} to `include` are not available.
Available cases are {self.models} and you wanted to include
{include}
"""
        return include

    def plot_improvement(
            self,
            metric_name: str,
            plot_type: str = 'dumbell',
            save: bool = True,
            name : str = '',
            dpi : int = 200,
            **kwargs
    ) -> pd.DataFrame:
        """
        Shows how much improvement was observed after hyperparameter
        optimization. This plot is only available if ``run_type`` was set to
        `optimize` in :py:meth:`ai4water.experiments.Experiments.fit`.

        Arguments
        ---------
            metric_name :
                the peformance metric for comparison
            plot_type : str, optional
                the kind of plot to draw. Either ``dumbell`` or ``bar``
            save : bool
                whether to save the plot or not
            name : str, optional
            dpi : int, optional
            **kwargs :
                any additional keyword arguments for
                `dumbell plot <https://easy-mpl.readthedocs.io/en/latest/plots.html#easy_mpl.dumbbell_plot>`_
                 or `bar_chart <https://easy-mpl.readthedocs.io/en/latest/plots.html#easy_mpl.bar_chart>`_

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> from ai4water.experiments import MLRegressionExperiments
        >>> from ai4water.datasets import busan_beach
        >>> experiment = MLRegressionExperiments()
        >>> experiment.fit(data=busan_beach(), run_type="optimize", num_iterations=30)
        >>> experiment.plot_improvement('r2')

        or draw dumbell plot

        >>> experiment.plot_improvement('r2', plot_type='bar')

        """

        data: str = 'test'

        assert data in ['training', 'test', 'validation']

        improvement = pd.DataFrame(columns=['start', 'end'])

        for model, model_iter_metrics in self.iter_metrics.items():
            initial = model_iter_metrics[0][metric_name]
            final = self.metrics[model]['test'][metric_name]

            key = shred_model_name(model)

            improvement.loc[key] = [initial, final]

        if plot_type == "dumbell":
            ax = dumbbell_plot(
                improvement['start'], improvement['end'],
                improvement.index.tolist(),
                xlabel=ERROR_LABELS.get(metric_name, metric_name),
                show=False,
                **kwargs
            )
            ax.set_xlabel(ERROR_LABELS.get(metric_name, metric_name))
        else:

            colors = {
                'start': np.array([0, 56, 104]) / 256,
                'end': np.array([126, 154, 178]) / 256
            }

            order = ['start', 'end']
            if metric_name in ['r2', 'nse', 'kge', 'corr_coeff', 'r2_mod', 'r2_score']:
                order = ['end', 'start']

            fig, ax = plt.subplots()

            for ordr in order:
                bar_chart(improvement[ordr], improvement.index.tolist(),
                          ax=ax, color=colors[ordr], show=False,
                          xlabel=ERROR_LABELS.get(metric_name, metric_name),
                          label=ordr, **kwargs)

            ax.legend()
            plt.title('Improvement after Optimization')

        if save:
            fname = os.path.join(
                os.getcwd(),
                f'results{SEP}{self.exp_name}{SEP}{name}_improvement_{metric_name}.png')
            plt.savefig(fname, dpi=dpi, bbox_inches=kwargs.get('bbox_inches', 'tight'))

        plt.show()

        return improvement

    def compare_errors(
            self,
            matric_name: str,
            cutoff_val: float = None,
            cutoff_type: str = None,
            save: bool = True,
            sort_by: str = 'test',
            ignore_nans: bool = True,
            name: str = 'ErrorComparison',
            show: bool = True,
            **kwargs
    ) -> pd.DataFrame:
        """
        Plots a specific performance matric for all the models which were
        run during [fit][ai4water.experiments.Experiments.fit] call.

        Parameters
        ----------
            matric_name:
                 performance matric whose value to plot for all the models
            cutoff_val:
                 if provided, only those models will be plotted for whome the
                 matric is greater/smaller than this value. This works in conjuction
                 with `cutoff_type`.
            cutoff_type:
                 one of ``greater``, ``greater_equal``, ``less`` or ``less_equal``.
                 Criteria to determine cutoff_val. For example if we want to
                 show only those models whose $R^2$ is > 0.5, it will be 'max'.
            save:
                whether to save the plot or not
            sort_by:
                either ``test`` or ``train``. How to sort the results for plotting.
                If 'test', then test performance matrics will be sorted otherwise
                train performance matrics will be sorted.
            ignore_nans:
                default True, if True, then performance matrics with nans are ignored
                otherwise nans/empty bars will be shown to depict which models have
                resulted in nans for the given performance matric.
            name:
                name of the saved file.
            show : whether to show the plot at the end or not?

            kwargs :

                - fig_height :
                - fig_width :
                - title_fs :
                - xlabel_fs :
                - color :

        returns
        -------
        pd.DataFrame
            pandas dataframe whose index is models and has two columns with name
            'train' and 'test' These columns contain performance metrics for the
            models..

        Example
        -------
            >>> from ai4water.experiments import MLRegressionExperiments
            >>> from ai4water.datasets import busan_beach
            >>> data = busan_beach()
            >>> inputs = list(data.columns)[0:-1]
            >>> outputs = list(data.columns)[-1]
            >>> experiment = MLRegressionExperiments(input_features=inputs, output_features=outputs)
            >>> experiment.fit(data=data)
            >>> experiment.compare_errors('mse')
            >>> experiment.compare_errors('r2', 0.2, 'greater')
        """

        models = self.sort_models_by_metric(matric_name, cutoff_val, cutoff_type,
                                            ignore_nans, sort_by)

        plt.close('all')
        fig, axis = plt.subplots(1, 2, sharey='all')
        fig.set_figheight(kwargs.get('fig_height', 8))
        fig.set_figwidth(kwargs.get('fig_width', 8))

        bar_chart(ax=axis[0],
                  labels=models.index.tolist(),
                  values=models['train'],
                  color=kwargs.get('color', None),
                  title="Train",
                  xlabel=ERROR_LABELS.get(matric_name, matric_name),
                  xlabel_fs=kwargs.get('xlabel_fs', 16),
                  title_fs=kwargs.get('title_fs', 20),
                  show=False,
                  )

        bar_chart(ax=axis[1],
                  labels=models.index.tolist(),
                  values=models['test'],
                  title="Test",
                  color=kwargs.get('color', None),
                  xlabel=ERROR_LABELS.get(matric_name, matric_name),
                  xlabel_fs=kwargs.get('xlabel_fs', 16),
                  title_fs=kwargs.get('title_fs', 20),
                  show_yaxis=False,
                  show=False
                  )

        appendix = f"{cutoff_val or ''}{cutoff_type or ''}{len(models)}"
        if save:
            fname = os.path.join(
                os.getcwd(),
                f'results{SEP}{self.exp_name}{SEP}{name}_{matric_name}_{appendix}.png')
            plt.savefig(fname, dpi=100, bbox_inches=kwargs.get('bbox_inches', 'tight'))

        if show:
            plt.show()
        return models

    def loss_comparison(
            self,
            loss_name: str = 'loss',
            include: list = None,
            save: bool = True,
            show: bool = True,
            figsize: int = None,
            start: int = 0,
            end: int = None,
            **kwargs
    ) -> plt.Axes:
        """
        Plots the loss curves of the evaluated models. This method is only available
        if the models which are being compared are deep leanring mdoels.

        Parameters
        ----------
            loss_name : str, optional
                the name of loss value, must be recorded during training
            include:
                name of models to include
            save:
                whether to save the plot or not
            show:
                whether to show the plot or now
            figsize : tuple
                size of the figure
            **kwargs :
                any other keyword arguments to be passed to the 
                `plot <https://easy-mpl.readthedocs.io/en/latest/plots.html#easy_mpl.plot>`_
        Returns
        -------
            matplotlib axes

        Example
        -------
        >>> from ai4water.experiments import DLRegressionExperiments
        >>> from ai4water.datasets import busan_beach
        >>> data = busan_beach()
        >>> exp = DLRegressionExperiments(
        >>> input_features = data.columns.tolist()[0:-1],
        >>> output_features = data.columns.tolist()[-1:],
        >>> epochs=300,
        >>> train_fraction=1.0,
        >>> y_transformation="log",
        >>> x_transformation="minmax",
        >>> )

        >>> exp.fit(data=data)
        >>> exp.loss_comparison()

        you may wish to plot on log scale

        >>> exp.loss_comparison(logy=True)
        """

        include = self._check_include_arg(include)

        loss_curves = {}
        for _model, _path in self.config['eval_models'].items():
            if _model in include:
                df = pd.read_csv(os.path.join(_path, 'losses.csv'), usecols=[loss_name])
                loss_curves[_model] = df.values

        _kwargs = {'linestyle': '-',
                   'xlabel': "Epochs",
                   'ylabel': 'Loss'}

        if len(loss_curves) > 5:
            _kwargs['legend_kws'] = {'bbox_to_anchor': (1.1, 0.99)}

        end = end or len(df)

        _, axis = plt.subplots(figsize=figsize)

        for _model, _loss in loss_curves.items():
            label = shred_model_name(_model)
            plot(_loss[start:end], ax=axis, label=label, show=False, **_kwargs, **kwargs)

        if save:
            fname = os.path.join(self.exp_path, f'loss_comparison_{loss_name}.png')
            plt.savefig(fname, dpi=100, bbox_inches='tight')

        if show:
            plt.show()

        return axis

    def compare_convergence(
            self,
            show: bool = True,
            save: bool = False,
            name: str = 'convergence_comparison',
            **kwargs
    ) -> Union[plt.Axes, None]:
        """
        Plots and compares the convergence plots of hyperparameter optimization runs.
        Only valid if `run_type=optimize` during :py:meth:`ai4water.experiments.Experiments.fit`
        call.

        Parameters
        ----------
            show :
                whether to show the plot or now
            save :
                whether to save the plot or not
            name :
                name of file to save the plot
            kwargs :
                keyword arguments to plot_ function
        Returns
        -------
            if the optimized models are >1 then it returns the maplotlib axes
            on which the figure is drawn otherwise it returns None.

        Examples
        --------
        >>> from ai4water.experiments import MLRegressionExperiments
        >>> from ai4water.datasets import busan_beach
        >>> experiment = MLRegressionExperiments()
        >>> experiment.fit(data=busan_beach(), run_type="optimize", num_iterations=30)
        >>> experiment.compare_convergence()

        .. _plot:
            https://easy-mpl.readthedocs.io/en/latest/plots.html#easy_mpl.plot
        """
        if len(self.config['optimized_models']) < 1:
            print('No model was optimized')
            return
        plt.close('all')
        fig, axis = plt.subplots()

        for _model, opt_path in self.config['optimized_models'].items():
            with open(os.path.join(opt_path, 'iterations.json'), 'r') as fp:
                iterations = json.load(fp)

            convergence = sort_array(list(iterations.keys()))

            label = shred_model_name(_model)
            plot(
                convergence,
                ax=axis,
                label=label,
                linestyle='--',
                xlabel='Number of iterations $n$',
                ylabel=r"$\min f(x)$ after $n$ calls",
                show=False,
                **kwargs
            )
        if save:
            fname = os.path.join(self.exp_path, f'{name}.png')
            plt.savefig(fname, dpi=100, bbox_inches='tight')

        if show:
            plt.show()
        return axis

    @classmethod
    def from_config(
            cls,
            config_path: str,
            **kwargs
    ) -> "Experiments":
        """
        Loads the experiment from the config file.

        Arguments:
            config_path : complete path of experiment
            kwargs : keyword arguments to experiment
        Returns:
            an instance of `Experiments` class
        """
        if not config_path.endswith('.json'):
            raise ValueError(f"""
{config_path} is not a json file
""")
        with open(config_path, 'r') as fp:
            config = json.load(fp)

        cls.config = config
        cls._from_config = True

        cv_scores = {}
        scoring = "mse"

        for model_name, model_path in config['eval_models'].items():

            with open(os.path.join(model_path, 'config.json'), 'r') as fp:
                model_config = json.load(fp)

            # if cross validation was performed, then read those results.
            cross_validator = model_config['config']['cross_validator']
            if cross_validator is not None:
                cv_name = str(list(cross_validator.keys())[0])
                scoring = model_config['config']['val_metric']
                cv_fname = os.path.join(model_path, f'{cv_name}_{scoring}' + ".json")
                if os.path.exists(cv_fname):
                    with open(cv_fname, 'r') as fp:
                        cv_scores[model_name] = json.load(fp)

        cls.metrics = load_json_file(
            os.path.join(os.path.dirname(config_path), "metrics.json"))
        cls.features = load_json_file(
            os.path.join(os.path.dirname(config_path), "features.json"))
        cls.cv_scores_ = cv_scores
        cls._cv_scoring = scoring

        return cls(exp_name=config['exp_name'], cases=config['cases'], **kwargs)

    def plot_cv_scores(
            self,
            show: bool = False,
            name: str = "cv_scores",
            exclude: Union[str, list] = None,
            include: Union[str, list] = None,
            **kwargs
    ) -> Union[plt.Axes, None]:
        """
        Plots the box whisker plots of the cross validation scores.

        This plot is only available if cross_validation was set to True during
        :py:meth:`ai4water.experiments.Experiments.fit`.

        Arguments
        ---------
            show : whether to show the plot or not
            name : name of the plot
            include : models to include
            exclude : models to exclude
            kwargs : any of the following keyword arguments

                - notch
                - vert
                - figsize
                - bbox_inches

        Returns
        -------
            matplotlib axes if the figure is drawn otherwise None

        Example
        -------
        >>> from ai4water.experiments import MLRegressionExperiments
        >>> from ai4water.datasets import busan_beach
        >>> exp = MLRegressionExperiments(cross_validator={"KFold": {"n_splits": 10}})
        >>> exp.fit(data=busan_beach(), cross_validate=True)
        >>> exp.plot_cv_scores()

        """
        if len(self.cv_scores_) == 0:
            return

        scoring = self._cv_scoring
        cv_scores = self.cv_scores_

        consider_exclude(exclude, self.models, cv_scores)
        cv_scores = self._consider_include(include, cv_scores)

        model_names = [m.split('model_')[1] for m in list(cv_scores.keys())]
        if len(model_names) < 5:
            rotation = 0
        else:
            rotation = 90

        plt.close()

        _, axis = plt.subplots(figsize=kwargs.get('figsize', (8, 6)))

        d = axis.boxplot(list(cv_scores.values()),
                         notch=kwargs.get('notch', None),
                         vert=kwargs.get('vert', None),
                         labels=model_names
                         )

        whiskers = d['whiskers']
        caps = d['caps']
        boxes = d['boxes']
        medians = d['medians']
        fliers = d['fliers']

        axis.set_xticklabels(model_names, rotation=rotation)
        axis.set_xlabel("Models", fontsize=16)
        axis.set_ylabel(ERROR_LABELS.get(scoring, scoring), fontsize=16)

        fname = os.path.join(os.getcwd(),
                             f'results{SEP}{self.exp_name}{SEP}{name}_{len(model_names)}.png')
        plt.savefig(fname, dpi=300, bbox_inches=kwargs.get('bbox_inches', 'tight'))

        if show:
            plt.show()

        return axis

    def sort_models_by_metric(
            self,
            metric_name,
            cutoff_val=None,
            cutoff_type=None,
            ignore_nans: bool = True,
            sort_by="test"
    ) -> pd.DataFrame:
        """returns the models sorted according to their performance"""

        idx = list(self.metrics.keys())
        train_metrics = [v['train'][metric_name] for v in self.metrics.values()]
        test_metrics = [v['test'][metric_name] for v in self.metrics.values()]

        df = pd.DataFrame(np.vstack((train_metrics, test_metrics)).T,
                          index=idx,
                          columns=['train', 'test'])
        if ignore_nans:
            df = df.dropna()

        df = df.sort_values(by=[sort_by], ascending=False)

        if cutoff_type is not None:
            assert cutoff_val is not None
            if cutoff_type=="greater":
                df = df.loc[df[sort_by]>cutoff_val]
            else:
                df = df.loc[df[sort_by]<cutoff_val]

        return df

    def fit_with_tpot(
            self,
            data,
            models: Union[int, List[str], dict, str] = None,
            selection_criteria: str = 'mse',
            scoring: str = None,
            **tpot_args
    ):
        """
        Fits the tpot_'s fit  method which
        finds out the best pipline for the given data.

        Arguments
        ---------
            data :
            models :
                It can be of three types.

                - If list, it will be the names of machine learning models/
                    algorithms to consider.
                - If integer, it will be the number of top
                    algorithms to consider for tpot. In such a case, you must have
                    first run `.fit` method before running this method. If you run
                    the tpot using all available models, it will take hours to days
                    for medium sized data (consisting of few thousand examples). However,
                    if you run first .fit and see for example what are the top 5 models,
                    then you can set this argument to 5. In such a case, tpot will search
                    pipeline using only the top 5 algorithms/models that have been found
                    using .fit method.
                - if dictionary, then the keys should be the names of algorithms/models
                    and values shoudl be the parameters for each model/algorithm to be
                    optimized.
                - You can also set it to ``all`` consider all models available in
                    ai4water's Experiment module.
                - default is None, which means, the `tpot_config` argument will be None

            selection_criteria :
                The name of performance metric. If ``models`` is integer, then
                according to this performance metric the models will be choosen.
                By default the models will be selected based upon their mse values
                on test data.
            scoring : the performance metric to use for finding the pipeline.
            tpot_args :
                any keyword argument for tpot's Regressor_ or Classifier_ class.
                This can include arguments like ``generations``, ``population_size`` etc.

        Returns
        -------
            the tpot object

        Example
        -------
            >>> from ai4water.experiments import MLRegressionExperiments
            >>> from ai4water.datasets import busan_beach
            >>> exp = MLRegressionExperiments(exp_name=f"tpot_reg_{dateandtime_now()}")
            >>> exp.fit(data=busan_beach())
            >>> tpot_regr = exp.fit_with_tpot(busan_beach(), 2, generations=1, population_size=2)

        .. _tpot:
            http://epistasislab.github.io/tpot/

        .. _Regressor:
            http://epistasislab.github.io/tpot/api/#regression

        .. _Classifier:
            http://epistasislab.github.io/tpot/api/#classification
        """
        tpot_caller = self.tpot_estimator
        assert tpot_caller is not None, f"tpot must be installed"

        param_space = {}
        tpot_config = None
        for m in self.models:
            getattr(self, m)()
            ps = getattr(self, 'param_space')
            path = getattr(self, 'path')
            param_space[m] = {path: {p.name: p.grid for p in ps}}

        if isinstance(models, int):

            assert len(self.metrics)>1, f"""
            you must first run .fit() method in order to choose top {models} models"""

            # sort the models w.r.t their performance
            sorted_models = self.sort_models_by_metric(selection_criteria)

            # get names of models
            models = sorted_models.index.tolist()[0:models]

            tpot_config = {}
            for m in models:
                c: dict = param_space[f"{m}"]
                tpot_config.update(c)

        elif isinstance(models, list):

            tpot_config = {}
            for m in models:
                c: dict = param_space[f"model_{m}"]
                tpot_config.update(c)

        elif isinstance(models, dict):

            tpot_config = {}
            for mod_name, mod_paras in models.items():

                if "." in mod_name:
                    mod_path = mod_name
                else:
                    c: dict = param_space[f"model_{mod_name}"]
                    mod_path = list(c.keys())[0]
                d = {mod_path: mod_paras}
                tpot_config.update(d)

        elif isinstance(models, str) and models == "all":
            tpot_config = {}
            for mod_name, mod_config in param_space.items():
                mod_path = list(mod_config.keys())[0]
                mod_paras = list(mod_config.values())[0]
                tpot_config.update({mod_path: mod_paras})

        fname = os.path.join(self.exp_path, "tpot_config.json")
        with open(fname, 'w') as fp:
            json.dump(jsonize(tpot_config), fp, indent=True)

        tpot = tpot_caller(
            verbosity=self.verbosity+1,
            scoring=scoring,
            config_dict=tpot_config,
            **tpot_args
        )

        not_allowed_args = ["cross_validator", "wandb_config", "val_metric",
                            "loss", "optimizer", "lr", "epochs", "quantiles", "patience"]
        model_kws = self.model_kws
        for arg in not_allowed_args:
            if arg in model_kws:
                model_kws.pop(arg)

        dh = DataSet(data, **model_kws)
        train_x, train_y = dh.training_data()
        tpot.fit(train_x, train_y.reshape(-1, 1))

        visualizer = ProcessResults(path=self.exp_path)

        for idx, data_name in enumerate(['training', 'test']):

            x_data, y_data = getattr(dh, f"{data_name}_data")(key=str(idx))

            pred = tpot.fitted_pipeline_.predict(x_data)
            r2 = RegressionMetrics(y_data, pred).r2()

            # todo, perform inverse transform and deindexification
            visualizer.plot_results(
                pd.DataFrame(y_data.reshape(-1,)),
                pd.DataFrame(pred.reshape(-1,)),
                annotation_key='$R^2$', annotation_val=r2,
                show=self.verbosity,
                where='',  name=data_name
            )
        # save the python code of fitted pipeline
        tpot.export(os.path.join(self.exp_path, "tpot_fitted_pipeline.py"))

        # save each iteration
        fname = os.path.join(self.exp_path, "evaludated_individuals.json")
        with open(fname, 'w') as fp:
            json.dump(tpot.evaluated_individuals_, fp, indent=True)
        return tpot

    def _build_and_run(self,
        data,
        predict=True,
        view=False,
        title=None,
        cross_validate=False,
        **kwargs):

        """
        Builds and run one 'model' of the experiment.

        Since an experiment consists of many models, this method
        is also run many times.
        """
        model = self._build(title=title, **kwargs)

        self._fit(data=data, cross_validate=cross_validate)

        if view:
            model.view()

        if predict:
            return self._predict(data=data)

        # return the validation score
        return self._evaluate()

    def _build(self, title=None, **suggested_paras):
        """Builds the ai4water Model class"""

        suggested_paras = jsonize(suggested_paras)

        verbosity = max(self.verbosity-1, 0)
        if 'verbosity' in self.model_kws:
            verbosity = self.model_kws.pop('verbosity')

        model = Model(
            prefix=title,
            verbosity=verbosity,
            **self.model_kws,
            **suggested_paras
        )

        setattr(self, 'model_', model)
        return

    def _fit(self, data, cross_validate=False):
        """Trains the model"""

        if cross_validate:
            return self.model_.cross_val_score(data=data,
                scoring = self.model_.config['val_metric'])

        return self.model_.fit(data=data)

    def _evaluate(self, data="validation")->float:
        """Evaluates the model"""

        t, p = self.model_.predict(
            data=data,
            return_true=True,
            process_results=False)

        metrics = Metrics[self.mode](t, p,
            remove_zero=True, remove_neg=True,
            multiclass=self.model_.is_multiclass)

        test_metrics = {}
        for metric in self.monitor:
            test_metrics[metric] = getattr(metrics, metric)()
        self.model_iter_metric[self.iter_] = test_metrics
        self.iter_ += 1

        val_score = getattr(metrics, self.model_.val_metric)()

        if self.model_.config['val_metric'] in [
            'r2', 'nse', 'kge', 'r2_mod', 'r2_adj', 'r2_score', 'accuracy', 'f1_score']:
            val_score = 1.0 - val_score
        
        if not math.isfinite(val_score):
            val_score = 9999  # TODO, find a better way to handle this

        print(f"val_score: {val_score}")
        return val_score

    def _predict(self, data):
        """Makes predictions on training and test data from the model.
        It is supposed that the model has been trained before."""

        test_true, test_pred = self.model_.predict(data=data, return_true=True)

        train_true, train_pred = self.model_.predict(data='training', return_true=True)

        return (train_true, train_pred), (test_true, test_pred)


class TransformationExperiments(Experiments):
    """Helper class to conduct experiments with different transformations

        Example:
            >>> from ai4water.datasets import busan_beach
            >>> from ai4water.experiments import TransformationExperiments
            >>> from ai4water.hyperopt import Integer, Categorical, Real
            ... # Define your experiment
            >>> class MyTransformationExperiments(TransformationExperiments):
            ...
            ...    def update_paras(self, **kwargs):
            ...        _layers = {
            ...            "LSTM": {"config": {"units": int(kwargs['lstm_units']}},
            ...            "Dense": {"config": {"units": 1, "activation": kwargs['dense_actfn']}},
            ...            "reshape": {"config": {"target_shape": (1, 1)}}
            ...        }
            ...        return {'model': {'layers': _layers},
            ...                'lookback': int(kwargs['lookback']),
            ...                'batch_size': int(kwargs['batch_size']),
            ...                'lr': float(kwargs['lr']),
            ...                'transformation': kwargs['transformation']}
            >>> data = busan_beach()
            >>> inputs = ['tide_cm', 'wat_temp_c', 'sal_psu', 'air_temp_c', 'pcp_mm', 'pcp3_mm']
            >>> outputs = ['tetx_coppml']
            >>> cases = {'model_minmax': {'transformation': 'minmax'},
            ...         'model_zscore': {'transformation': 'zscore'}}
            >>> search_space = [
            ...            Integer(low=16, high=64, name='lstm_units', num_samples=2),
            ...            Integer(low=3, high=15, name="lookback", num_samples=2),
            ...            Categorical(categories=[4, 8, 12, 16, 24, 32], name='batch_size'),
            ...            Real(low=1e-6, high=1.0e-3, name='lr', prior='log', num_samples=2),
            ...            Categorical(categories=['relu', 'elu'], name='dense_actfn'),
            ...        ]
            >>> x0 = [20, 14, 12, 0.00029613, 'relu']
            >>> experiment = MyTransformationExperiments(cases=cases, input_features=inputs,
            ...                output_features=outputs, exp_name="testing"
            ...                 param_space=search_space, x0=x0)
    """

    @property
    def mode(self):
        return "regression"

    def __init__(self,
                 param_space=None,
                 x0=None,
                 cases: dict = None,
                 exp_name: str = None,
                 num_samples: int = 5, 
                 verbosity: int = 1,
                 **model_kws):
        self.param_space = param_space
        self.x0 = x0
        self.model_kws = model_kws

        exp_name = exp_name or 'TransformationExperiments' + f'_{dateandtime_now()}'

        super().__init__(cases=cases,
                         exp_name=exp_name,
                         num_samples=num_samples,
                         verbosity=verbosity)

    @property
    def tpot_estimator(self):
        return None

    def update_paras(self, **suggested_paras):
        raise NotImplementedError(f"""
You must write the method `update_paras` which should build the Model with suggested parameters
and return the keyword arguments including `model`. These keyword arguments will then
be used to build ai4water's Model class.
""")

    def _build(self, title=None, **suggested_paras):
        """Builds the ai4water Model class"""

        suggested_paras = jsonize(suggested_paras)

        verbosity = max(self.verbosity-1, 0)
        if 'verbosity' in self.model_kws:
            verbosity = self.model_kws.pop('verbosity')

        model = Model(
            prefix=title,
            verbosity=verbosity,
            **self.update_paras(**suggested_paras),
            **self.model_kws
        )

        setattr(self, 'model_', model)
        return

    def build_from_config(self, data, config_path, weight_file, **kwargs):

        model = Model.from_config_file(config_path=config_path)
        weight_file = os.path.join(model.w_path, weight_file)
        model.update_weights(weight_file=weight_file)

        model = self.process_model_before_fit(model)

        train_true, train_pred = model.predict(data=data, return_true=True)

        test_true, test_pred = model.predict(data='test', return_true=True)

        model.dh_.config['allow_nan_labels'] = 1
        model.predict()

        return (train_true, train_pred), (test_true, test_pred)

    def process_model_before_fit(self, model):
        """So that the user can perform procesisng of the model by overwriting this method"""
        return model


def sort_array(array):
    """
    array: [4, 7, 3, 9, 4, 8, 2, 8, 7, 1]
    returns: [4, 4, 3, 3, 3, 3, 2, 2, 2, 1]
    """
    results = np.array(array, dtype=np.float32)
    iters = range(1, len(results) + 1)
    return [np.min(results[:i]) for i in iters]


def consider_exclude(exclude: Union[str, list], 
        models, 
        models_to_filter: Union[list, dict] = None):

    if isinstance(exclude, str):
        exclude = [exclude]

    if exclude is not None:
        exclude = ['model_' + _model if not _model.startswith('model_') else _model for _model in exclude]
        for elem in exclude:
            assert elem in models, f"""
                {elem} to `exclude` is not available.
                Available models are {models} and you wanted to exclude
                {exclude}"""

            if models_to_filter is not None:
                assert elem in models_to_filter, f'{elem} is not in models'
                if isinstance(models_to_filter, list):
                    models_to_filter.remove(elem)
                else:
                    models_to_filter.pop(elem)
    return


def load_json_file(fpath):

    with open(fpath, 'r') as fp:
        result = json.load(fp)
    return result


def save_json_file(fpath, obj):

    with open(fpath, 'w') as fp:
        json.dump(jsonize(obj), fp)


def shred_model_name(model_name):
    key = model_name[6:] if model_name.startswith('model_') else model_name
    key = key[0:-9] if key.endswith("Regressor") else key
    return key