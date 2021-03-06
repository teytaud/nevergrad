# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import typing as tp
from functools import partial
import numpy as np
import sklearn.datasets
from sklearn.tree import DecisionTreeRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.model_selection import train_test_split, KFold
from sklearn.metrics import mean_squared_error

from nevergrad.parametrization import parameter as p
from ..base import ExperimentFunction


# pylint: disable=too-many-instance-attributes,too-many-locals,too-many-arguments
class MLTuning(ExperimentFunction):
    """Class for generating ML hyperparameter tuning problems.
    We propose different possible regressors and different dimensionalities.
    In each case, Nevergrad will optimize the parameters of a scikit learning.

    Parameters
    ----------
    regressor: str
        type of function we can use for doing the regression. Can be "mlp", "decision_tree", "decision_tree_depth", "any".
        "any" means that the regressor has one more parameter which is a discrete choice among possibilities.
    data_dimension: int
        dimension of the data we generate. None if not an artificial dataset.
    dataset: str
        type of dataset; can be diabetes, boston, artificial, artificialcoos, artificialsquare.
    overfitter: bool
        if we want the evaluation to be the same as during the optimization run. This means that instead
        of train/valid/error, we have train/valid/valid. This is for research purpose, when we want to check if an algorithm
        is particularly good or particularly bad because it fails to minimize the validation loss or because it overfits.

    """

    # Example of ML problem.
    def _ml_parametrization(
        self,
        depth: int,  # Parameters for regression trees.
        criterion: str,
        min_samples_split: float,
        solver: str,  # Parameters for neural nets.
        activation: str,
        alpha: float,
        learning_rate: str,
        regressor: str,  # Choice of learner.
        noise_free: bool  # Whether we work on the test set (the real cost) on an approximation (CV error on train). -> not really noise
    ) -> float:
        if not self.X.size:  # lazzy initialization
            self.make_dataset(self.data_dimension, self.dataset)
        # num_cv-folds cross-validation
        result = 0.0
        # Fit regression model
        if regressor == "decision_tree":
            regr = DecisionTreeRegressor(max_depth=depth, criterion=criterion,
                                         min_samples_split=min_samples_split, random_state=0)
        elif regressor == "mlp":
            regr = MLPRegressor(alpha=alpha, activation=activation, solver=solver,
                                learning_rate=learning_rate, random_state=0)
        else:
            raise ValueError(f"Unknown regressor {regressor}.")

        if noise_free:  # noise_free is True when we want the result on the test set.
            X = self.X_train
            y = self.y_train
            X_test = self.X_test
            y_test = self.y_test
            regr.fit(np.asarray(self.X), np.asarray(self.y))
            pred_test = regr.predict(self.X_test)
            return mean_squared_error(self.y_test, pred_test)

        # We do a cross-validation.
        for X, y, X_test, y_test in zip(self.X_train_cv, self.y_train_cv, self.X_valid_cv, self.y_valid_cv):
            assert isinstance(depth, int), f"depth has class {type(depth)} and value {depth}."

            regr.fit(np.asarray(X), np.asarray(y))

            # Predict
            pred_test = regr.predict(X_test)
            result += mean_squared_error(y_test, pred_test)

        return result / self._cross_val_num  # We return a num_cv-fold validation error.

    def __init__(
        self,
        regressor: str,
        data_dimension: tp.Optional[int] = None,
        dataset: str = "artificial",
        overfitter: bool = False
    ) -> None:
        self.regressor = regressor
        self.data_dimension = data_dimension
        self.dataset = dataset
        self.overfitter = overfitter
        self._descriptors: tp.Dict[str, tp.Any] = {}
        self.add_descriptors(regressor=regressor, data_dimension=data_dimension, dataset=dataset, overfitter=overfitter)
        self.name = regressor + f"Dim{data_dimension}"
        self.num_data = 120  # default for artificial function
        self._cross_val_num = 10  # number of cross validation
        # Dimension does not make sense if we use a real world dataset.
        assert bool("artificial" in dataset) == bool(data_dimension is not None)

        # Variables for storing the training set and the test set.
        self.X: np.ndarray = np.array([])
        self.y: np.ndarray

        # Variables for storing the cross-validation splits.
        self.X_train_cv: tp.List[tp.Any] = []  # This will be the list of training subsets.
        self.X_valid_cv: tp.List[tp.Any] = []  # This will be the list of validation subsets.
        self.y_train_cv: tp.List[tp.Any] = []
        self.y_valid_cv: tp.List[tp.Any] = []
        self.X_train: np.ndarray
        self.y_train: np.ndarray
        self.X_test: np.ndarray
        self.y_test: np.ndarray

        evalparams: tp.Dict[str, tp.Any] = {}
        if regressor == "decision_tree_depth":
            # Only the depth, as an evaluation.
            parametrization = p.Instrumentation(depth=p.Scalar(lower=1, upper=1200).set_integer_casting())
            # We optimize only the depth, so we fix all other parameters than the depth
            params = dict(noise_free=False, criterion="mse",
                          min_samples_split=0.00001,
                          regressor="decision_tree",
                          alpha=1.0, learning_rate="no",
                          activation="no", solver="no")
        elif regressor == "any":
            # First we define the list of parameters in the optimization
            parametrization = p.Instrumentation(
                depth=p.Scalar(lower=1, upper=1200).set_integer_casting(),  # Depth, in case we use a decision tree.
                criterion=p.Choice(["mse", "friedman_mse", "mae"]),  # Criterion for building the decision tree.
                min_samples_split=p.Log(lower=0.0000001, upper=1),  # Min ratio of samples in a node for splitting.
                regressor=p.Choice(["mlp", "decision_tree"]),  # Type of regressor.
                activation=p.Choice(["identity", "logistic", "tanh", "relu"]),  # Activation function, in case we use a net.
                solver=p.Choice(["lbfgs", "sgd", "adam"]),  # Numerical optimizer.
                learning_rate=p.Choice(["constant", "invscaling", "adaptive"]),  # Learning rate schedule.
                alpha=p.Log(lower=0.0000001, upper=1.),  # Complexity penalization.
            )
            # noise_free is False (meaning that we consider the cross-validation loss) during the optimization.
            params = dict(noise_free=False)
        elif regressor == "decision_tree":
            # We specify below the list of hyperparameters for the decision trees.
            parametrization = p.Instrumentation(
                depth=p.Scalar(lower=1, upper=1200).set_integer_casting(),
                criterion=p.Choice(["mse", "friedman_mse", "mae"]),
                min_samples_split=p.Log(lower=0.0000001, upper=1),
                regressor="decision_tree",
            )
            params = dict(noise_free=False,
                          alpha=1.0, learning_rate="no", regressor="decision_tree",
                          activation="no", solver="no")
            evalparams = dict(params, criterion="mse", min_samples_split=0.00001)
        elif regressor == "mlp":
            # Let us define the parameters of the neural network.
            parametrization = p.Instrumentation(
                activation=p.Choice(["identity", "logistic", "tanh", "relu"]),
                solver=p.Choice(["lbfgs", "sgd", "adam"]),
                regressor="mlp",
                learning_rate=p.Choice(["constant", "invscaling", "adaptive"]),
                alpha=p.Log(lower=0.0000001, upper=1.),
            )
            params = dict(noise_free=False, regressor="mlp", depth=-3, criterion="no", min_samples_split=0.1)
        else:
            assert False, f"Problem type {regressor} undefined!"
        # build eval params if not specified
        if not evalparams:
            evalparams = dict(params)
        # For the evaluation we remove the noise (unless overfitter)
        evalparams["noise_free"] = not overfitter
        super().__init__(partial(self._ml_parametrization, **params), parametrization.set_name(""))
        self._evalparams = evalparams
        self.register_initialization(regressor=regressor, data_dimension=data_dimension, dataset=dataset,
                                     overfitter=overfitter)

    def evaluation_function(self, *args: tp.Any, **kwargs: tp.Any) -> float:
        assert not args
        # override with eval parameters (with partial, the eval parameters would be overriden by kwargs)
        kwargs.update(self._evalparams)
        return self._ml_parametrization(**kwargs)

    def make_dataset(self, data_dimension: tp.Optional[int], dataset: str) -> None:
        # Filling datasets.
        rng = self.parametrization.random_state
        if not dataset.startswith("artificial"):
            assert dataset in ["boston", "diabetes"]
            assert data_dimension is None
            data = {"boston": sklearn.datasets.load_boston,
                    "diabetes": sklearn.datasets.load_diabetes,
                    }[dataset](return_X_y=True)

            # Half the dataset for training.
            rng.shuffle(data[0].T)  # We randomly shuffle the columns.
            self.X = data[0]
            self.y = data[1]
            self.X_train, self.X_test, self.y_train, self.y_test = train_test_split(self.X, self.y, test_size=0.5, random_state=42)
            num_train_data = len(self.X_train)
            self.num_data = num_train_data

            kf = KFold(n_splits=self._cross_val_num)
            kf.get_n_splits(self.X_train)

            for train_index, valid_index in kf.split(self.X_train):
                self.X_train_cv += [self.X_train[train_index]]
                self.y_train_cv += [self.y_train[train_index]]
                self.X_valid_cv += [self.X_train[valid_index]]
                self.y_valid_cv += [self.y_train[valid_index]]
            return

        assert data_dimension is not None, f"Pb with {dataset} in dimension {data_dimension}"

        # Training set.
        X = np.arange(0., 1., 1. / (self.num_data * data_dimension))
        X = X.reshape(-1, data_dimension)
        rng.shuffle(X)

        target_function = {
            "artificial": np.sin,
            "artificialcos": np.cos,
            "artificialsquare": np.square,
        }[dataset]
        y = np.sum(np.sin(X), axis=1).ravel()
        self.X = X
        self.y = y
        self.X_train = X  # Training set.
        self.y_train = y  # Labels of the training set.

        # We generate the cross-validation subsets.
        for cv in range(self._cross_val_num):

            # Training set.
            X_train_cv = X[np.arange(self.num_data) % self._cross_val_num != cv].copy()
            y_train_cv = np.sum(target_function(X_train_cv), axis=1).ravel()
            self.X_train_cv += [X_train_cv]
            self.y_train_cv += [y_train_cv]

            # Validation set or test set (noise_free is True for test set).
            X_valid_cv = X[np.arange(self.num_data) % self._cross_val_num == cv].copy()
            X_valid_cv = X_valid_cv.reshape(-1, data_dimension)
            y_valid_cv = np.sum(target_function(X_valid_cv), axis=1).ravel()
            self.X_valid_cv += [X_valid_cv]
            self.y_valid_cv += [y_valid_cv]

        # We also generate the test set.
        X_test = np.arange(0., 1., 1. / 60000)
        rng.shuffle(X_test)
        X_test = X_test.reshape(-1, data_dimension)
        y_test = np.sum(target_function(X_test), axis=1).ravel()
        self.X_test = X_test
        self.y_test = y_test
        