
from typing import Union

from ai4water.utils.utils import Jsonize
from ai4water.backend import np, skopt, optuna
from ai4water.backend import hyperopt as hp

if hp is not None:
    space_eval = hp.space_eval
else:
    hp = None

_Real = skopt.space.Real
_Integer = skopt.space.Integer
_Categorical = skopt.space.Categorical

if optuna is not None:
    CategoricalDistribution = optuna.distributions.CategoricalDistribution
    UniformDistribution = optuna.distributions.UniformDistribution
    IntLogUniformDistribution = optuna.distributions.IntLogUniformDistribution
    IntUniformDistribution = optuna.distributions.IntUniformDistribution
    LogUniformDistribution = optuna.distributions.LogUniformDistribution
else:
    CategoricalDistribution = None
    UniformDistribution = None
    IntLogUniformDistribution = None
    IntUniformDistribution = None
    LogUniformDistribution = None


# helper class to be able to print [1, ..., 4] instead of [1, '...', 4]
class _Ellipsis:
    def __repr__(self):
        return '...'


class Dummy:
    def __init__(self, low=None, high=None, *args, **kwargs):
        self.low = low
        self.high = high


if _Real is None:
    class _Real(Dummy): pass
    class _Integer(Dummy): pass
    class _Categorical(Dummy): pass


class Real(_Real):
    """
    This class is used for the parameters which have fractional values
    such as real values from 1.0 to 3.5.
    This class extends the `Real` class of Skopt so that it has an attribute grid which then
    can be fed to optimization algorithm to create grid space. It also adds several further
    methods to it.

    Attributes
    ------------
    grid

    Methods
    ----------
    - as_hp
    - to_optuna
    - suggest
    - to_optuna
    - serialize

    Example
    -------
        >>> from ai4water.hyperopt import Real
        >>> lr = Real(low=0.0005, high=0.01, prior='log', name='lr')
    """
    counter = 0
    def __init__(self,
                 low: float = None,
                 high: float = None,
                 num_samples: int = None,
                 step: int = None,
                 grid: Union[list, np.ndarray] = None,
                 *args,
                 **kwargs
                 ):
        """
        Arguments:
            low : lower limit of parameter
            high : upper limit of parameter
            step : used to define `grid` in conjuction with `low` and `high`
            grid : array like, if given, `low`, `high`, `step` and `num_samples`
                will be redundant.
            num_samples : if given, it will be used to create grid space using the formula
        """
        if low is None:
            assert grid is not None
            assert hasattr(grid, '__len__')
            low = np.min(grid)
            high = np.max(grid)

        self.counter += 1
        if 'name' not in kwargs:
            kwargs['name'] = f'real_{self.counter}'

        if skopt is not None:
            kwargs = check_prior(kwargs)

        self.num_samples = num_samples
        self.step = step
        super().__init__(low=low, high=high, *args, **kwargs)
        self.grid = grid

    @property
    def grid(self):
        return self._grid

    @grid.setter
    def grid(self, x):
        if x is None:
            if self.num_samples:
                self._grid = np.linspace(self.low, self.high, self.num_samples)
            elif self.step:
                self._grid = np.arange(self.low, self.high, self.step)
            else:
                self._grid = None
        else:
            self._grid = np.array(x)

    def as_hp(self, as_named_args=True):

        if self.prior == 'log-uniform':
            return hp.loguniform(self.name, low=self.low, high=self.high)
        else:
            assert self.prior in ['uniform', 'loguniform', 'normal', 'lognormal',
                                  'quniform', 'qloguniform', 'qnormal', 'qlognormal']
            if as_named_args:
                return getattr(hp, self.prior)(label=self.name, low=self.low, high=self.high)
            else:
                return getattr(hp, self.prior)(self.name, self.low, self.high)

    def suggest(self, _trial):
        # creates optuna trial
        log = False
        if self.prior:
            if self.prior == 'log':
                log = True

        return _trial.suggest_float(name=self.name,
                                    low=self.low,
                                    high=self.high,
                                    step=self.step,  # default step is None
                                    log=log)

    def to_optuna(self):
        """returns an equivalent optuna space"""
        if self.prior != 'log':
            return UniformDistribution(low=self.low, high=self.high)
        else:
            return LogUniformDistribution(low=self.low, high=self.high)

    def serialize(self):
        """Serializes the `Real` object so that it can be saved in json"""
        _raum = {k: Jsonize(v)() for k, v in self.__dict__.items() if not callable(v)}
        _raum.update({'type': 'Real'})
        return _raum

    def __repr__(self):
        return f"Real(low={self.low}, high={self.high}," \
               f" prior='{self.prior}', transform='{self.transform_}' name='{self.name}')"


class Integer(_Integer):
    """
    This class is used when the parameter is integer such as integer values from 1 to 10.
    Extends the Real class of Skopt so that it has an attribute grid which then
    can be fed to optimization algorithm to create grid space. Moreover it also
    generates optuna and hyperopt compatible/equivalent instances.

    Attributes
    ------------
    grid

    Methods
    ----------
    - as_hp
    - to_optuna
    - suggest
    - to_optuna
    - serialize

    Example:
        >>> from ai4water.hyperopt import Integer
        >>> units = Integer(low=16, high=128, name='units')

    """
    counter = 0
    def __init__(self,
                 low: int = None,
                 high: int = None,
                 num_samples: int = None,
                 step: int = None,
                 grid: "np.ndarray, list" = None,
                 *args,
                 **kwargs
                 ):
        """
        Arguments:
            low : lower limit of parameter
            high : upper limit of parameter
            grid list/array: If given, `low` and `high` should not be given as they will be
                calculated from this grid.
            step int: if given , it will be used to calculated grid using the formula
                np.arange(low, high, step)
            num_samples int: if given, it will be used to create grid space using the formula
                np.linspace(low, high, num_samples)
        """

        if low is None:
            assert grid is not None
            assert hasattr(grid, '__len__')
            low = np.min(grid)
            high = np.max(grid)

        self.counter += 1
        if 'name' not in kwargs:
            kwargs['name'] = f'integer_{self.counter}'

        self.num_samples = num_samples
        self.step = step

        if skopt is not None:
            kwargs = check_prior(kwargs)

        super().__init__(low=low, high=high, *args, **kwargs)
        self.grid = grid

    @property
    def grid(self):
        return self._grid

    @grid.setter
    def grid(self, x):
        if x is None:
            if self.num_samples:
                __grid = np.linspace(self.low, self.high, self.num_samples, dtype=np.int32)
                self._grid = [int(val) for val in __grid]
            elif self.step:
                __grid = np.arange(self.low, self.high, self.step, dtype=np.int32)
                self._grid = [int(val) for val in __grid]
            else:
                self._grid = None
        else:
            assert hasattr(x, '__len__'), f"unacceptable type of grid {x.__class__.__name__}"
            self._grid = np.array(x)

    def as_hp(self, as_named_args=True):
        if as_named_args:
            return hp.randint(self.name, low=self.low, high=self.high)
        else:
            return hp.randint(self.name, self.low, self.high)

    def suggest(self, _trial):
        # creates optuna trial
        log = False
        if self.prior:
            if self.prior == 'log':
                log = True

        return _trial.suggest_int(name=self.name,
                                  low=self.low,
                                  high=self.high,
                                  step=self.step if self.step else 1,  # default step is 1
                                  log=log)

    def to_optuna(self):
        """returns an equivalent optuna space"""
        if self.prior != 'log':
            return IntUniformDistribution(low=self.low, high=self.high)
        else:
            return IntLogUniformDistribution(low=self.low, high=self.high)

    def serialize(self):
        """Serializes the `Integer` object so that it can be saved in json"""
        _raum = {k: Jsonize(v)() for k, v in self.__dict__.items() if not callable(v)}
        _raum.update({'type': 'Integer'})
        return _raum

    def __repr__(self):
        return f"Integer(low={self.low}, high={self.high}," \
               f" prior='{self.prior}', transform='{self.transform_}' name='{self.name}')"


class Categorical(_Categorical):
    """
    This class is used when parameter has distinct group/class of values such
    as [1,2,3] or ['a', 'b', 'c']. This class overrides skopt's `Categorical` class.
    It Can be converted to optuna's distribution or hyper_opt's choice. It uses
    same input arguments as received by skopt's `Categorical`_ class

    Methods
    ----------
    - as_hp
    - to_optuna
    - suggest
    - to_optuna
    - serialize

    Example
    -------
        >>> from ai4water.hyperopt import Categorical
        >>> activations = Categorical(categories=['relu', 'tanh', 'sigmoid'], name='activations')


    .. _Categorical:
        https://scikit-optimize.github.io/stable/modules/generated/skopt.space.space.Categorical.html
    """
    @property
    def grid(self):
        return self.categories

    def as_hp(self, as_named_args=True):
        categories = self.categories
        if isinstance(categories, tuple):
            categories = list(self.categories)
        return hp.choice(self.name, categories)

    def suggest(self, _trial):
        # creates optuna trial
        return _trial.suggest_categorical(name=self.name, choices=self.categories)

    def to_optuna(self):
        return CategoricalDistribution(choices=self.categories)

    def serialize(self):
        """Serializes the `Categorical object` so that it can be saved in json"""
        _raum = {k: Jsonize(v)() for k, v in self.__dict__.items() if not callable(v)}
        _raum.update({'type': 'Integer'})
        return _raum

    def __repr__(self):
        if len(self.categories) > 7:
            cats = self.categories[:3] + (_Ellipsis(),) + self.categories[-3:]
        else:
            cats = self.categories

        if self.prior is not None and len(self.prior) > 7:
            prior = self.prior[:3] + [_Ellipsis()] + self.prior[-3:]
        else:
            prior = self.prior

        return f"Categorical(categories={cats}, prior={prior} name='{self.name}')"


def check_prior(kwargs: dict):
    prior = kwargs.get('prior', 'uniform')
    if prior in ["log"] and skopt.__version__ in ["0.9.0"]:
        # todo see why this will give error
        kwargs['prior'] = "log-uniform"
    return kwargs
