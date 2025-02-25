
from typing import Union, Callable

from ai4water.backend import os, np, pd, plt, plotly

from .plotting_tools import save_or_show, to_1d_array


class Plot(object):

    def __init__(self, path=None, backend='plotly', save=True, dpi=300):
        self.path = path
        self.backend = backend
        self.save = save
        self.dpi = dpi

    @property
    def backend(self):
        return self._backend

    @backend.setter
    def backend(self, x):

        _backend = x
        assert x in ['plotly', 'matplotlib'], f"unknown backend {x}. Allowed values are `plotly` and `matplotlib`"

        if x == 'plotly':
            if plotly is None:
                _backend = 'matplotlib'

        self._backend = _backend

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, x):
        if x is None:
            x = os.getcwd()
        self._path = x

    def save_or_show(self, save: bool = None, fname=None, where='', dpi=None, bbox_inches='tight',
                     close=True, show=False):

        if save is None:
            save = self.save

        if dpi is None:
            dpi = self.dpi

        return save_or_show(self.path, save, fname, where, dpi, bbox_inches, close, show=show)


def linear_model(
        model_name: str,
        inputs,
        target
):
    import sklearn
    from ai4water.backend import get_attributes

    models = get_attributes(sklearn, "linear_model", case_sensitive=True)
    if model_name not in models:
        raise ValueError(f"Can not find {model_name} in sklearn.linear_model")
    model = models[model_name]
    reg = model().fit(inputs, target)

    return reg.predict(inputs)


def murphy_diagram(
        observed: Union[list, np.ndarray, pd.Series, pd.DataFrame],
        predicted: Union[list, np.ndarray, pd.Series, pd.DataFrame],
        reference: Union[list, np.ndarray, pd.Series, pd.DataFrame] = None,
        reference_model: Union[str, Callable] = None,
        inputs=None,
        plot_type: str = "scores",
        xaxis: str = "theta",
        ax: plt.Axes = None,
        line_colors: tuple = None,
        fill_color: str = "lightgray",
        show: bool = True
) -> plt.Axes:
    """Murphy diagram as introducted by Ehm_ et al., 2015
     and illustrated by Rob Hyndman_

    Arguments:
        observed:
            observed or true values
        predicted:
             model's prediction
        reference:
             reference prediction
        reference_model:
             The model for reference prediction. Only relevent if `reference` is
             None and `plot_type` is `diff`. It can be callable or a string. If it is a
             string, then it can be any model name from sklearn.linear_model_
        inputs:
             inputs for reference model. Only relevent if `reference_model` is not
             None and `plot_type` is `diff`
        plot_type:
             either of `scores` or `diff`
        xaxis:
             either of `theta` or `time`
        ax:
             the axis to use for plotting
        line_colors:
             colors of line
        fill_color:
             color to fill confidence interval
        show:
             whether to show the plot or not

    Returns:
         matplotlib axes

    Example:
        >>> import numpy as np
        >>> from ai4water.utils.visualizations import murphy_diagram
        >>> yy = np.random.randint(1, 1000, 100)
        >>> ff1 = np.random.randint(1, 1000, 100)
        >>> ff2 = np.random.randint(1, 1000, 100)
        >>> murphy_diagram(yy, ff1, ff2)
        ...
        >>> murphy_diagram(yy, ff1, ff2, plot_type="diff")

    .. _Ehm:
        https://arxiv.org/pdf/1503.08195.pdf

    .. _Hyndman:
        https://robjhyndman.com/hyndsight/murphy-diagrams/

    .. _sklearn.linear_model:
        https://scikit-learn.org/stable/modules/classes.html#module-sklearn.linear_model
    """
    assert plot_type in ("scores", "diff")
    assert xaxis in ("theta", "time")

    y = to_1d_array(observed)
    f1 = to_1d_array(predicted)

    if reference is None:
        if plot_type == "diff":
            assert reference_model is not None
            if callable(reference_model):
                reference = reference_model(inputs)
            else:
                assert inputs is not None, f"You must specify the inputs for {reference_model}"
                reference = linear_model(reference_model, inputs, predicted)
            f2 = to_1d_array(reference)
        else:
            f2 = None
    else:
        f2 = to_1d_array(reference)

    line_colors = line_colors or ["dimgrey", "tab:orange"]

    n = len(y)
    _min, _max = np.nanmin(np.hstack([y, f1, f2])), np.nanmax(np.hstack([y, f1, f2]))
    tmp = _min-0.2*(_max-_min), _max+0.2*(_max-_min)

    theta = np.linspace(tmp[0], tmp[1], 501)

    s1 = np.full((501, n), np.nan)
    s2 = np.full((501, n), np.nan)

    max1 = np.maximum(f1, y)
    max2 = np.maximum(f2, y)

    min1 = np.minimum(f1, y)
    min2 = np.minimum(f2, y)

    for j in range(n):

        s1[:, j] = abs(y[j]-theta) * (max1[j] > theta) * (min1[j] <= theta)
        s2[:, j] = abs(y[j] - theta) * (max2[j] > theta) * (min2[j] <= theta)

    # grab the axes
    if ax is None:
        ax = plt.gca()

    if xaxis == "theta":
        s1ave, s2ave = _data_for_theta(s1, s2)
    else:
        raise NotImplementedError

    if plot_type == "scores":
        _plot_scores(theta, s1ave, s2ave, ax, line_colors)
        ax.set_ylabel("Empirical Scores", fontsize=16)
    else:
        _plot_diff(theta, s1, s2, n, ax, line_colors[0], fill_color)
        ax.set_ylabel("Difference in scores", fontsize=16)

    ax.set_xlabel(xaxis, fontsize=16)

    if show:
        plt.show()

    return ax


def last_nonzero(arr, axis, invalid_val=-1):
    mask = arr != 0
    val = arr.shape[axis] - np.flip(mask, axis=axis).argmax(axis=axis) - 1
    return np.where(mask.any(axis=axis), val, invalid_val)


def _plot_diff(theta, s1, s2, n, ax, line_color="black", fill_color="lightgray"):

    se = np.std(s1-s2)/np.sqrt(n)

    diff = np.mean(s1-s2, axis=1)

    upper = diff + 1.96 * se
    lower = diff - 1.96 * se

    ax.plot(theta, diff, color=line_color)

    # first_nonzero occurence
    st = (diff != 0).argmax(axis=0)
    en = last_nonzero(diff, axis=0).item()

    ax.fill_between(theta[st:en], upper[st:en], lower[st:en],  # alpha=0.2,
                    color=fill_color)

    return ax


def fdc_plot(
        sim: Union[list, np.ndarray, pd.Series, pd.DataFrame],
        obs: Union[list, np.ndarray, pd.Series, pd.DataFrame],
        ax: plt.Axes = None,
        legend: bool = True,
        xlabel: str = "Exceedence [%]",
        ylabel: str = "Flow",
        show: bool = True
) -> plt.Axes:
    """Plots flow duration curve

    Arguments:
        sim:
            simulated flow
        obs:
            observed flow
        ax:
            axis on which to plot
        legend:
            whether to apply legend or not
        xlabel:
            label to set on x-axis. set to None for no x-label
        ylabel:
            label to set on y-axis
        show:
            whether to show the plot or not

    Returns:
        matplotlib axes

    Example:
        >>> import numpy as np
        >>> import matplotlib.pyplot as plt
        >>> from ai4water.utils.visualizations import fdc_plot
        >>> simulated = np.random.random(100)
        >>> observed = np.random.random(100)
        >>> fdc_plot(simulated, observed)
        >>> plt.show()
    """

    sim = to_1d_array(sim)
    obs = to_1d_array(obs)

    sort_obs = np.sort(sim)[::-1]
    exceedence_obs = np.arange(1., len(sort_obs)+1) / len(sort_obs)
    sort_sim = np.sort(obs)[::-1]
    exceedence_sim = np.arange(1., len(sort_sim)+1) / len(sort_sim)

    if ax is None:
        ax = plt.gca()

    ax.plot(exceedence_obs * 100, sort_obs, color='b', label="Observed")
    ax.plot(exceedence_sim * 100, sort_sim, color='r', label="Simulated")

    if legend:
        ax.legend()

    if xlabel is not None:
        ax.set_xlabel(xlabel)
    if ylabel is not None:
        ax.set_ylabel(ylabel)

    if show:
        plt.show()

    return ax


def _plot_scores(theta, s1ave, s2ave, ax, line_colors):

    ax.plot(theta, s1ave, color=line_colors[0])
    ax.plot(theta, s2ave, color=line_colors[1])

    return ax


def _data_for_time(s1, s2):
    s1ave, s2ave = np.mean(s1, axis=0), np.mean(s2, axis=0)

    return s1ave, s2ave


def _data_for_theta(s1, s2):
    return np.mean(s1, axis=1), np.mean(s2, axis=1)

def init_subplots(width=None, height=None, nrows=1, ncols=1, **kwargs):
    """Initializes the fig for subplots"""
    plt.close('all')
    fig, ax = plt.subplots(nrows=nrows, ncols=ncols, **kwargs)
    if width is not None:
        fig.set_figwidth(width)
    if height is not None:
        fig.set_figheight(height)
    return fig, ax