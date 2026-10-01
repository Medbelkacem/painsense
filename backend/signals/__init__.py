"""EEG and EMG acquisition, signal quality, feature extraction and analysis.

The module records signals, measures their quality, derives features from them, and offers
those features to an inference service. What it does not do is produce a pain score of its
own. No EEG or EMG pain model is trained in this platform, and the analysis says so in
those words rather than returning a number.

That split is deliberate and load-bearing. Recording and feature extraction are honest
signal processing and work whether or not a model exists. Pain estimation is a separate
claim requiring a model trained on labelled data, and the absence of one is reported as an
absence.
"""
