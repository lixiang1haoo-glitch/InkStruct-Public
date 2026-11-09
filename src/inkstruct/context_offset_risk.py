"""Regularized author/component offsets for frozen numerical risk models."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .grouped_logistic_risk import fit_grouped, group_weights, sigmoid


def category_keys(row, mode):
    if mode not in ('author', 'component', 'hierarchical'):
        raise ValueError('unknown context mode')
    writer, context = row['writer'], row['context']
    if not isinstance(writer, str) or not writer or not isinstance(context, str) or not context:
        raise ValueError('writer and public component context required')
    author, component = ('author', writer), ('component', context)
    if mode == 'author':
        return [author]
    if mode == 'component':
        return [component]
    return [author, component, ('author_component', writer, context)]


def design(rows, vocabulary, mode):
    lookup = {key: i for i, key in enumerate(vocabulary)}
    x = np.zeros((len(rows), len(vocabulary)))
    for i, row in enumerate(rows):
        for key in category_keys(row, mode):
            if key in lookup:
                x[i, lookup[key]] = 1.
    return x


@dataclass
class ContextOffset:
    mode: str
    regularization: float
    vocabulary: list
    coefficients: np.ndarray
    iterations: int
    gradient_max: float

    def offset(self, rows):
        return design(rows, self.vocabulary, self.mode)@self.coefficients

    def payload(self):
        return {'mode': self.mode, 'regularization': self.regularization,
                'vocabulary': [list(k) for k in self.vocabulary], 'coefficients': self.coefficients.tolist(),
                'iterations': self.iterations, 'gradient_max': self.gradient_max}


def fit_offset(rows, base_logits, *, mode, regularization):
    if not np.isfinite(regularization) or regularization <= 0:
        raise ValueError('positive regularization required')
    w = group_weights(rows)
    y = np.asarray([r['safe_benefit'] for r in rows], dtype=float)
    offset = np.asarray(base_logits, dtype=float)
    if offset.shape != (len(rows),) or not np.isfinite(offset).all() or not np.isin(y, [0., 1.]).all():
        raise ValueError('finite base logits and binary targets required')
    vocabulary = sorted({key for row in rows for key in category_keys(row, mode)})
    x = design(rows, vocabulary, mode)
    beta = np.zeros(len(vocabulary))

    def objective(b):
        eta = offset+x@b
        return float(w@(np.logaddexp(0., eta)-y*eta)+.5*regularization*(b@b))

    for iteration in range(100):
        p = sigmoid(offset+x@beta)
        gradient = x.T@(w*(p-y))+regularization*beta
        if np.max(np.abs(gradient)) < 1e-8:
            break
        hessian = x.T@((w*p*(1-p))[:, None]*x)+np.eye(len(beta))*regularization
        step = np.linalg.solve(hessian, gradient)
        loss, alpha = objective(beta), 1.
        while alpha > 1e-10:
            trial = beta-alpha*step
            if objective(trial) <= loss-1e-4*alpha*float(gradient@step):
                beta = trial
                break
            alpha /= 2
        else:
            raise RuntimeError('context offset line search failed')
    gradient = x.T@(w*(sigmoid(offset+x@beta)-y))+regularization*beta
    error = float(np.max(np.abs(gradient)))
    if not np.isfinite(beta).all() or error > 1e-6:
        raise RuntimeError('context offset optimizer did not converge')
    return ContextOffset(mode, regularization, vocabulary, beta, iteration+1, error)


def base_logits(model, features):
    # Models expose probabilities; clipping protects logit conversion without
    # changing practical scores at the fixed 0.8 decision boundary.
    p = np.clip(model.predict(features), 1e-12, 1-1e-12)
    return np.log(p)-np.log1p(-p)


class ContextRiskGate:
    def __init__(self, examples, *, mode='base', regularization=None):
        keys = [(r['writer'], r['character'], r['component_id'], r['proposal_id']) for r in examples]
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate training proposal')
        if mode not in ('base', 'author', 'component', 'hierarchical'):
            raise ValueError('unknown context mode')
        self.examples = sorted(examples, key=lambda r: (r['writer'], r['character'], r['component_id'], r['proposal_id']))
        self.mode, self.regularization, self.cache = mode, regularization, {}

    def predict(self, writer, character, context, features, *, threshold=.8):
        if not 0 <= threshold <= 1:
            raise ValueError('invalid threshold')
        if character not in self.cache:
            rows = [r for r in self.examples if r['character'] != character]
            model = fit_grouped(rows, view='combined', regularization=.1)
            correction = fit_offset(rows, base_logits(model, [r['features'] for r in rows]), mode=self.mode,
                regularization=self.regularization) if self.mode != 'base' else None
            self.cache[character] = model, correction, rows
        model, correction, rows = self.cache[character]
        base_score = float(model.predict([features])[0])
        query = {'writer': writer, 'context': context}
        delta = float(correction.offset([query])[0]) if correction is not None else 0.
        score = float(sigmoid(base_logits(model, [features])[0]+delta)) if correction is not None else base_score
        peers = {(r['writer'], r['character']) for r in rows if r['writer'] == writer and r['context'] == context}
        return {'policy': 'context_offset_risk_v1', 'available': True, 'accepted': score >= threshold,
                'score': score, 'base_score': base_score, 'logit_offset': delta, 'threshold': threshold,
                'mode': self.mode, 'regularization': self.regularization, 'same_author_context_characters': len(peers),
                'training_rows': len(rows), 'query_character_excluded': True}
