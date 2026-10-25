# SPDX-License-Identifier: MIT
"""Explicit text classification using the bundled float32-input TFLM model."""

_SEQUENCE_LENGTH = 50
_LABEL_COUNT = 11
_DEFAULT_ARENA_SIZE = 256 * 1024
_DEFAULT_TEXTS = (
    'fitness exercise health patient',
    'mechanical trusses device',
    'career joined attended helped',
)


def _directory():
    return __file__.replace('\\', '/').rsplit('/', 1)[0]


def _join(directory, name):
    return directory.rstrip('/\\') + '/' + name


class Tokenizer:
    """Lowercase, whitespace split, original line IDs, truncate, right-pad."""

    def __init__(self, vocab_path):
        self.vocab = {}
        with open(vocab_path, 'r') as stream:
            for index, line in enumerate(stream):
                word = line.strip()
                if index == 0 and word != '':
                    raise ValueError('vocab line 0 must be empty (padding)')
                if index == 1 and word != '[UNK]':
                    raise ValueError('vocab line 1 must be [UNK]')
                if word:
                    if word in self.vocab:
                        raise ValueError('duplicate vocabulary token')
                    self.vocab[word] = index
        if self.vocab.get('[UNK]') != 1:
            raise ValueError('vocab must contain padding and [UNK] lines')

    def encode(self, text):
        if not isinstance(text, str):
            raise TypeError('text must be a string')
        ids = [self.vocab.get(word, 1) for word in text.lower().split()[:_SEQUENCE_LENGTH]]
        return ids + [0] * (_SEQUENCE_LENGTH - len(ids))


def _load_labels(path):
    with open(path, 'r') as stream:
        labels = [line.strip() for line in stream]
    if len(labels) != _LABEL_COUNT or any(not label for label in labels):
        raise ValueError('labels must contain exactly 11 nonempty lines')
    if len(set(labels)) != _LABEL_COUNT:
        raise ValueError('labels must be unique')
    return labels


class Classifier:
    """Own one model; close explicitly or use a with block.

    path overrides the model only; directory supplies vocabulary and labels.
    Scores returned by classify are raw logits, not probabilities.
    """

    def __init__(self, path=None, directory=None, backend='reference',
                 arena_size=_DEFAULT_ARENA_SIZE):
        self._model = None
        if backend not in ('auto', 'reference', 'vc4'):
            raise ValueError('backend must be auto, reference, or vc4')
        if not isinstance(arena_size, int) or not 1024 <= arena_size <= 64 * 1024 * 1024:
            raise ValueError('arena_size must be 1024..67108864')
        location = _directory() if directory is None else directory
        self.tokenizer = Tokenizer(_join(location, 'vocab.txt'))
        self.labels = _load_labels(_join(location, 'labels.txt'))
        self.backend = backend
        from ml import Model
        try:
            self._model = Model(_join(location, 'text_cls_tflm.tflite') if path is None else path,
                                backend=backend, arena_size=arena_size)
            if (self._model.input_shape != ((1, _SEQUENCE_LENGTH),) or
                    self._model.output_shape != ((1, _LABEL_COUNT),) or
                    self._model.input_dtype != ('f',) or
                    self._model.output_dtype != ('f',)):
                raise ValueError('expected float32 input [1,50] and output [1,11]')
        except BaseException:
            self.close()
            raise

    def classify(self, text, top_k=3):
        """Return [(label, raw_logit), ...] in descending score order."""
        if self._model is None:
            raise RuntimeError('classifier is closed')
        if not isinstance(top_k, int) or not 1 <= top_k <= _LABEL_COUNT:
            raise ValueError('top_k must be 1..11')
        from ulab import numpy as np
        # ulab np.float is float32 in this mpynn build. The model casts IDs internally.
        x = np.array(self.tokenizer.encode(text), dtype=np.float).reshape((1, _SEQUENCE_LENGTH))
        output = self._model.predict([x])[0]
        if tuple(output.shape) != (1, _LABEL_COUNT):
            raise ValueError('expected output [1,11]')
        scores = []
        for index, label in enumerate(self.labels):
            score = float(output[0, index])
            if not abs(score) < float('inf'):
                raise ValueError('nonfinite output logit')
            scores.append((label, score))
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:top_k]

    def close(self):
        model = self._model
        self._model = None
        if model is not None:
            model.deinit()

    def __enter__(self):
        if self._model is None:
            raise RuntimeError('classifier is closed')
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


def run(texts=None, directory=None, backend='reference', arena_size=_DEFAULT_ARENA_SIZE):
    """Classify three known sentences by default; always release the model."""
    if texts is None:
        texts = _DEFAULT_TEXTS
    elif isinstance(texts, str):
        texts = (texts,)
    classifier = None
    try:
        classifier = Classifier(directory=directory, backend=backend, arena_size=arena_size)
        print('textcls backend request:', backend, '| scores: raw logits')
        if backend != 'reference':
            print('VC4 is not guaranteed: output depth 11 fails FC16; CPU fallback may apply.')
        results = []
        for text in texts:
            predictions = classifier.classify(text)
            print(text)
            for label, score in predictions:
                print('  %s: %.6f' % (label, score))
            results.append((text, predictions))
        return results
    finally:
        if classifier is not None:
            classifier.close()
