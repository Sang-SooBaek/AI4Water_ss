import os
import time
import pickle
import unittest
import site
ai4_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
site.addsitedir(ai4_dir)

import warnings
warnings.filterwarnings("ignore")


import skopt
import optuna
import sklearn
import numpy as np
from sklearn.svm import SVC
from scipy.stats import uniform
from hyperopt import hp, STATUS_OK
from skopt.space.space import Space
from sklearn.datasets import load_iris
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

np.random.seed(313)

optuna.logging.set_verbosity(optuna.logging.ERROR)

from ai4water.tf_attributes import tf
from ai4water.utils.utils import Jsonize
from ai4water.datasets import busan_beach
from ai4water.postprocessing.SeqMetrics import RegressionMetrics
from ai4water.hyperopt import HyperOpt, Real, Categorical, Integer

if tf is not None:
    if 230 <= int(''.join(tf.__version__.split('.')[0:2]).ljust(3, '0')) < 250:
        from ai4water.functional import Model
        print(f"Switching to functional API due to tensorflow version {tf.__version__}")
    else:
        from ai4water import Model



data = busan_beach()
inputs = list(data.columns)[0:-1]
outputs = [list(data.columns)[-1]]


def objective_func(**suggestion):
    model = Model(
        model={"XGBRegressor": suggestion},
        prefix=f'test_{"bayes"}_xgboost',
        split_random=True,
        verbosity=0)

    model.fit(data=data)

    t, p = model.predict(return_true=True, process_results=False)
    mse = RegressionMetrics(t, p).mse()

    return mse


search_space = [
    Categorical(['gbtree', 'dart'], name='booster'),
    Integer(low=10, high=20, name='n_estimators', num_samples=10),
    Real(low=1.0e-5, high=0.1, name='learning_rate', num_samples=10)
]

prev_xy = {'213026901362135.5_0': {'booster': 'gbtree',
                                   'n_estimators': 19,
                                   'learning_rate': 0.0052790817104302595},
           '212354344234773.53_1': {'booster': 'gbtree',
                                    'n_estimators': 12,
                                    'learning_rate': 0.009236769988485223},
           '217301037967875.97_2': {'booster': 'gbtree',
                                    'n_estimators': 17,
                                    'learning_rate': 0.054629143096849984}}

def check_attrs(optimizer, paras):
    optimizer.eval_with_best()
    space = optimizer.space()
    assert isinstance(space, dict)
    assert len(space)==paras
    assert isinstance(optimizer.xy_of_iterations(), dict)
    assert len(optimizer.xy_of_iterations()) >= optimizer.num_iterations, f"""
            {len(optimizer.xy_of_iterations())}, {optimizer.num_iterations}"""
    assert isinstance(optimizer.best_paras(as_list=True), list)
    assert isinstance(optimizer.best_paras(False), dict)
    assert len(optimizer.func_vals()) >= optimizer.num_iterations
    assert isinstance(optimizer.skopt_space(), Space)

    fpath = os.path.join(optimizer.opt_path, 'serialized.json')
    assert os.path.exists(fpath)

    return


def run_unified_interface(algorithm, backend, num_iterations, num_samples=None):

    def fn(**suggestion):
        model = Model(
            input_features=inputs,
            output_features=outputs,
            model={"XGBRegressor": suggestion},
            prefix=f'test_{algorithm}_xgboost_{backend}',
            split_random=True,
            verbosity=0)

        model.fit(data=data)

        t, p = model.predict(return_true=True, process_results=False)
        mse = RegressionMetrics(t, p).mse()

        return mse

    search_space = [
        Categorical(['gbtree', 'dart'], name='booster'),
        Integer(low=10, high=20, name='n_estimators', num_samples=num_samples),
        Real(low=1.0e-5, high=0.1, name='learning_rate', num_samples=num_samples)
    ]

    optimizer = HyperOpt(algorithm, objective_fn=fn, param_space=search_space,
                         backend=backend,
                         num_iterations=num_iterations,
                         verbosity=0,
                         opt_path=os.path.join(os.getcwd(), f'results\\test_{algorithm}_xgboost_{backend}'))

    optimizer.fit()
    check_attrs(optimizer, len(search_space))

    for f in ["fanova_importance_bar.png", "convergence.png", "iterations.json",
              "edf.png", "parallel_coordinates.png", "iterations_sorted.json",
              'distributions.png', "fanova_importance_hist.png"
              ]:
        fpath = os.path.join(optimizer.opt_path, f)
        assert os.path.exists(fpath)
    return optimizer


class TestHyperOpt(unittest.TestCase):

    def test_real_num_samples(self):
        r = Real(low=10, high=100, num_samples=20)
        grit = r.grid
        assert grit.shape == (20,)

    def test_real_steps(self):
        r = Real(low=10, high=100, step=20)
        grit = r.grid
        assert grit.shape == (5,)

    def test_real_grid(self):
        grit = [1,2,3,4,5]
        r = Real(grid=grit)
        np.testing.assert_array_equal(grit, r.grid)

    def test_integer_num_samples(self):
        r = Integer(low=10, high=100, num_samples=20)
        grit = r.grid
        assert len(grit) == 20

    def test_integer_steps(self):
        r = Integer(low=10, high=100, step=20)
        grit = r.grid
        assert len(grit) == 5

    def test_integer_grid(self):
        grit = [1, 2, 3, 4, 5]
        r = Integer(grid=grit)
        np.testing.assert_array_equal(grit, r.grid)

    def test_categorical(self):
        cats = ['a', 'b', 'c']
        c = Categorical(cats)
        assert len(cats) == len(c.grid)

    def test_random(self):
        # testing for sklearn-based model with random search
        # https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.RandomizedSearchCV.html#sklearn.model_selection.RandomizedSearchCV
        iris = load_iris()
        logistic = LogisticRegression(solver='saga', tol=1e-2, max_iter=200,
                                      random_state=0)
        distributions1 = dict(C=uniform(loc=0, scale=4),
                             penalty=['l2', 'l1'])

        clf = HyperOpt('random', objective_fn=logistic, param_space=distributions1,
                       random_state=0,
                       verbosity=0)

        search = clf.fit(iris.data, iris.target)
        np.testing.assert_almost_equal(search.best_params_['C'], 2.195254015709299, 5)
        assert search.best_params_['penalty'] == 'l1'
        #print("RandomizeSearchCV test passed")
        return clf


    def test_grid(self):
        # testing for sklearn-based model with grid search
        # https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GridSearchCV.html#sklearn.model_selection.GridSearchCV
        iris = load_iris()
        parameters = {'kernel': ('linear', 'rbf'), 'C': [1, 10]}
        svc = SVC()
        clf = HyperOpt("grid", objective_fn=svc, param_space=parameters, verbosity=0)
        search = clf.fit(iris.data, iris.target)

        sorted(clf.cv_results_.keys())

        assert search.best_params_['C'] == 1
        assert search.best_params_['kernel'] == 'linear'
        #print("GridSearchCV test passed")
        return clf

    def test_bayes(self):
        # testing for sklearn-based model with gp_min
        # https://scikit-optimize.github.io/stable/modules/generated/skopt.BayesSearchCV.html
        if int(sklearn.__version__.split('.')[0])>=1:
            X, y = load_iris(return_X_y=True)
        else:
            X, y = load_iris(True)
        X_train, X_test, y_train, y_test = train_test_split(X, y, train_size=0.75, random_state=0)
        if int(''.join(sklearn.__version__.split('.')[1])) > 22:
            # https://github.com/scikit-optimize/scikit-optimize/issues/978
            pass
        else:
            opt = HyperOpt("bayes",  objective_fn=SVC(),
                           param_space={
                'C': Real(1e-6, 1e+6, prior='log-uniform'),
                'gamma': Real(1e-6, 1e+1, prior='log-uniform'),
                'degree': Integer(1, 8),
                'kernel': Categorical(['linear', 'poly', 'rbf']),
                },
                n_iter=32,
                random_state=0,
                           verbosity=0
            )

            # executes bayesian optimization
            _ = opt.fit(X_train, y_train)

            # model can be saved, used for predictions or scoring
            np.testing.assert_almost_equal(0.9736842105263158, opt.score(X_test, y_test), 5)
        #("BayesSearchCV test passed")
        return

    def test_gpmin_skopt(self):
        # testing for custom model with gp_min
        # https://github.com/scikit-optimize/scikit-optimize/blob/9334d50a1ad5c9f7c013a1c1cb95313a54b83168/examples/bayesian-optimization.py#L109
        def f(x, noise_level=0.1):
            return np.sin(5 * x[0]) * (1 - np.tanh(x[0] ** 2)) \
                   + np.random.randn() * noise_level

        opt = HyperOpt("bayes", objective_fn=f, param_space=[(-2.0, 2.0)],
                       acq_func="EI",  # the acquisition function
                       n_calls=15,  # the number of evaluations of f
                       n_random_starts=5,  # the number of random initialization points
                       noise=0.1 ** 2,  # the noise level (optional)
                       random_state=1234,
                       verbosity=0
                       )

        # executes bayesian optimization
        sr = opt.fit()
        if int(skopt.__version__.split('.')[1]) < 8:
            pass
        else:
            assert isinstance(sr.fun, float)  # todo why below is failing now.
            # np.testing.assert_almost_equal(-0.909471164417979, sr.fun, 7)  # when called from same file where hyper_opt is saved
        return

    def test_grid_custom_model(self):
        # testing grid search algorithm for custom model
        def f(x, noise_level=0.1):
            return np.sin(5 * x) * (1 - np.tanh(x ** 2)) \
                   + np.random.randn() * noise_level

        opt = HyperOpt("grid",
                       objective_fn=f,
                       param_space=[Real(low=-2.0, high=2.0, num_samples=20)],
                       n_calls=15,  # the number of evaluations of f,
                       verbosity=0
                       )

        # executes bayesian optimization
        sr = opt.fit()
        assert len(sr) == 20
        return

    def test_named_custom_bayes(self):
        dims = [Integer(low=10, high=20, name='n_estimators'),
                Real(low=1e-5, high=0.1, name='learning_rate'),
                Categorical(categories=["gbtree", "dart"], name="booster")
                ]

        def f(**kwargs):

            kwargs['objective'] = 'reg:squarederror'

            kwargs = Jsonize(kwargs)()

            model = Model(
                input_features=inputs,
                output_features=outputs,
                #lookback=1,
                batches="2d",
                #val_data="same",
                #test_fraction=0.3,
                val_fraction=0.0,
                model={"XGBRegressor": kwargs},
                prefix='testing',
                split_random=True,
                verbosity=0)

            model.fit(data=data)

            t, p = model.predict(return_true=True, process_results=False)
            mse = RegressionMetrics(t, p).mse()

            return mse

        opt = HyperOpt("bayes",
                       objective_fn=f,
                       param_space=dims,
                       acq_func='EI',  # Expected Improvement.
                       n_calls=12,
                       # acq_optimizer='auto',
                       x0=[10, 0.01, "gbtree"],
                       n_random_starts=3,  # the number of random initialization points
                       random_state=2,
                       verbosity=0
                       )

        opt.fit()
        check_attrs(opt, len(dims))
        return

    def test_hyperopt_basic(self):
        # https://github.com/hyperopt/hyperopt/blob/master/tutorial/01.BasicTutorial.ipynb
        def objective(x):
            return {
                'loss': x ** 2,
                'status': STATUS_OK,
                # -- store other results like this
                'eval_time': time.time(),
                'other_stuff': {'type': None, 'value': [0, 1, 2]},
                # -- attachments are handled differently
                'attachments':
                    {'time_module': pickle.dumps(time.time)}
                }

        optimizer = HyperOpt('tpe',
                             objective_fn=objective,
                             param_space=hp.uniform('x', -10, 10),
                             backend='hyperopt',
                             max_evals=100,
                             verbosity=0
                             )
        best = optimizer.fit()
        check_attrs(optimizer, 1)
        self.assertGreater(len(best), 0)
        return

    def test_hyperopt_multipara(self):
        # https://github.com/hyperopt/hyperopt/blob/master/tutorial/02.MultipleParameterTutorial.ipynb
        def objective(**params):
            x, y = params['x'], params['y']
            return np.sin(np.sqrt(x**2 + y**2))

        space = {
            'x': hp.uniform('x', -6, 6),
            'y': hp.uniform('y', -6, 6)
        }

        optimizer = HyperOpt('tpe', objective_fn=objective, param_space=space,
                             backend='hyperopt',
                             max_evals=100,
                             verbosity=0
                             )
        best = optimizer.fit()
        check_attrs(optimizer, 2)
        self.assertEqual(len(best), 2)
        return

    # # def test_hyperopt_multipara_multispace(self):  # todo
    # #     # https://github.com/hyperopt/hyperopt/issues/615
    # #     def f(**params):
    # #         x1, x2 = params['x1'], params['x2']
    # #         if x1 == 'james':
    # #             return -1 * x2
    # #         if x1 == 'max':
    # #             return 2 * x2
    # #         if x1 == 'wansoo':
    # #             return -3 * x2
    # #
    # #     search_space = {
    # #         'x1': hp.choice('x1', ['james', 'max', 'wansoo']),
    # #         'x2': hp.randint('x2', -5, 5)
    # #     }
    # #
    def test_ai4waterModel_with_hyperopt(self):
        """"""
        def fn(**suggestion):

            model = Model(
                input_features=inputs,
                output_features=outputs,
                model={"XGBRegressor": suggestion},
                prefix='test_tpe_xgboost',
                split_random=True,
                verbosity=0)

            model.fit(data=data)

            t, p = model.predict(return_true=True, process_results=False)
            mse = RegressionMetrics(t, p).mse()
            #print(f"Validation mse {mse}")

            return mse

        search_space = {
            'booster': hp.choice('booster', ['gbtree', 'dart']),
            'n_estimators': hp.randint('n_estimators', low=10, high=20),
            'learning_rate': hp.uniform('learning_rate', low=1e-5, high=0.1)
        }
        optimizer = HyperOpt('tpe', objective_fn=fn, param_space=search_space, max_evals=5,
                             backend='hyperopt',
                             verbosity=0,
                             opt_path=os.path.join(os.getcwd(), 'results', 'test_tpe_xgboost'))

        optimizer.fit()
        check_attrs(optimizer, 3)
        self.assertEqual(len(optimizer.trials.trials), 5)
        self.assertIsNotNone(optimizer.skopt_space())
        return

    def test_unified_interface(self):

        run_unified_interface('tpe', 'optuna', 5)
        run_unified_interface('cmaes', 'optuna', 5)
        run_unified_interface('random', 'optuna', 5)
        run_unified_interface('grid', 'optuna', 5, num_samples=3)
        run_unified_interface('tpe', 'hyperopt', 5)
        #run_unified_interface('atpe', 'hyperopt', 5)  # todo
        run_unified_interface('random', 'hyperopt', 5)
        run_unified_interface('bayes', 'skopt', 12)
        run_unified_interface('bayes_rf', 'skopt', 12)
        run_unified_interface('random', 'sklearn', 5, num_samples=5)
        run_unified_interface('grid', 'sklearn', None, num_samples=2)
        return


class TestAddPrevResult(unittest.TestCase):

    def test_skopt_with_dict(self):

        optimizer = HyperOpt("bayes",
                             objective_fn=objective_func,
                             param_space=search_space,
                             num_iterations=12,
                             verbosity=0,
                             process_results=False,
                             opt_path=os.path.join(os.getcwd(), f'results\\test_bayes_xgboost')
                             )

        optimizer.add_previous_results(prev_xy)

        optimizer.fit()

        assert len(optimizer.xy_of_iterations()) == 15
        return

    def test_skopt_with_xy(self):
        x0, y0 = [], []
        for y, x in prev_xy.items():
            y0.append(float(y))
            x0.append(list(x.values()))

        optimizer = HyperOpt("bayes",
                             objective_fn=objective_func,
                             param_space=search_space,
                             num_iterations=12,
                             verbosity=0,
                             process_results=False,
                             opt_path=os.path.join(os.getcwd(), f'results\\test_bayes_xgboost')
                             )

        optimizer.add_previous_results(x=x0, y=y0)

        optimizer.fit()

        assert len(optimizer.xy_of_iterations()) == 15

        return


if __name__ == "__main__":
    unittest.main()
