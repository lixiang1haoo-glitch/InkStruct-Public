"""Training-only calibrated feature comparison for fixed layout proposals."""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass

import numpy as np

VIEWS = {'layout': slice(0, 22), 'geometry': slice(22, 46), 'combined': slice(0, 46)}


def meta_fold(character):
    return int(hashlib.sha256(('layout-risk-meta-v1:'+character).encode()).hexdigest()[:8], 16) % 3


def group_weights(rows):
    counts = Counter((r['writer'], r['character']) for r in rows)
    if not counts:
        raise ValueError('empty training outcomes')
    weights = np.asarray([1/counts[r['writer'], r['character']] for r in rows])
    return weights/weights.sum()


def sigmoid(x):
    x = np.asarray(x, dtype=float)
    return np.exp(-np.logaddexp(0., -x))


@dataclass
class GroupedLogisticModel:
    view: str
    regularization: float
    center: np.ndarray
    scale: np.ndarray
    coefficients: np.ndarray
    iterations: int
    gradient_max: float

    def predict(self, features):
        x = np.asarray(features, dtype=float)
        if x.ndim != 2 or x.shape[1] != 46 or not np.isfinite(x).all():
            raise ValueError('expected finite 46-dimensional feature rows')
        z = np.clip((x[:, VIEWS[self.view]]-self.center)/self.scale, -5., 5.)
        return sigmoid(np.c_[np.ones(len(x)), z]@self.coefficients)

    def payload(self):
        return {'view': self.view, 'regularization': self.regularization,
                'center': self.center.tolist(), 'scale': self.scale.tolist(),
                'coefficients': self.coefficients.tolist(), 'iterations': self.iterations,
                'gradient_max': self.gradient_max}


def fit_grouped(rows, *, view='combined', regularization=.01):
    if view not in VIEWS or not np.isfinite(regularization) or regularization <= 0:
        raise ValueError('invalid model configuration')
    weights = group_weights(rows)
    x = np.asarray([r['features'] for r in rows], dtype=float)
    y = np.asarray([r['safe_benefit'] for r in rows], dtype=float)
    if x.shape != (len(rows), 46) or not np.isfinite(x).all() or not np.isin(y, [0., 1.]).all():
        raise ValueError('finite feature rows and binary targets required')
    x = x[:, VIEWS[view]]
    center = np.sum(weights[:, None]*x, axis=0)
    scale = np.maximum(np.sqrt(np.sum(weights[:, None]*(x-center)**2, axis=0)), .1)
    z = np.c_[np.ones(len(x)), np.clip((x-center)/scale, -5., 5.)]
    prior = np.clip(weights@y, 1e-8, 1-1e-8)
    beta = np.zeros(z.shape[1])
    beta[0] = np.log(prior/(1-prior))
    penalty = np.r_[0., np.full(z.shape[1]-1, regularization)]

    def objective(b):
        eta = z@b
        return float(weights@(np.logaddexp(0., eta)-y*eta)+.5*np.sum(penalty*b*b))

    for iteration in range(100):
        p = sigmoid(z@beta)
        gradient = z.T@(weights*(p-y))+penalty*beta
        if np.max(np.abs(gradient)) < 1e-8:
            break
        hessian = z.T@((weights*p*(1-p))[:, None]*z)+np.diag(penalty+1e-10)
        step = np.linalg.solve(hessian, gradient)
        loss = objective(beta)
        alpha = 1.
        while alpha > 1e-10:
            next_beta = beta-alpha*step
            if objective(next_beta) <= loss-1e-4*alpha*float(gradient@step):
                beta = next_beta
                break
            alpha /= 2
        else:
            raise RuntimeError('risk optimizer line search failed')
    gradient = z.T@(weights*(sigmoid(z@beta)-y))+penalty*beta
    error = float(np.max(np.abs(gradient)))
    if not np.isfinite(beta).all() or error > 1e-6:
        raise RuntimeError('risk optimizer did not converge')
    return GroupedLogisticModel(view, regularization, center, scale, beta, iteration+1, error)


def validation_cells(rows):
    """Share a source-isolated generation fold, then separate target characters."""
    for generation in range(3):
        subset = [r for r in rows if r['fold'] == generation]
        for heldout in range(3):
            train = [r for r in subset if meta_fold(r['character']) != heldout]
            valid = [r for r in subset if meta_fold(r['character']) == heldout]
            if not train or not valid:
                raise ValueError('empty source-isolated validation cell')
            yield generation, heldout, train, valid


class GroupedLogisticRiskGate:
    def __init__(self, examples, *, view, regularization):
        keys = [(r['writer'], r['character'], r['component_id'], r['proposal_id']) for r in examples]
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate grouped risk outcome')
        self.examples = sorted(examples, key=lambda r: (r['writer'], r['character'], r['component_id'], r['proposal_id']))
        self.view, self.regularization = view, regularization
        self.cache = {}

    def predict(self, character, features, *, threshold=.8):
        if not 0 <= threshold <= 1:
            raise ValueError('invalid score threshold')
        if character not in self.cache:
            rows = [r for r in self.examples if r['character'] != character]
            groups = {(r['writer'], r['character']) for r in rows}
            if len(groups) < 5:
                return {'accepted': False, 'available': False, 'reason': 'fewer than five training characters'}
            self.cache[character] = (fit_grouped(rows, view=self.view, regularization=self.regularization), len(rows), len(groups))
        model, n, groups = self.cache[character]
        score = float(model.predict([features])[0])
        return {'policy': 'grouped_logistic_risk_v1', 'available': True, 'accepted': score >= threshold,
                'score': score, 'threshold': threshold, 'view': self.view, 'regularization': self.regularization,
                'reference_count': groups, 'training_rows': n, 'query_character_excluded': True,
                'reason': 'training model supports frozen move' if score >= threshold else 'training model rejects frozen move'}
