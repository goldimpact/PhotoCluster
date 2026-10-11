"""Sampling identity shared by media, embeddings and completed match caches."""
from pathlib import Path


def dynamic(photo):
    return bool(photo.get('animated') or photo.get('media_type') == 'video')


def sampling_identity(photo):
    if not dynamic(photo):
        return ''  # Preserve compatible still-image descriptors.
    path = photo.get('frame_path')
    if photo.get('media_version', 0) >= 2 and path and Path(path).is_file():
        return 'sampled-frames-v2'
    return 'legacy-small-frames-v1'


def needs_refresh(photo):
    return dynamic(photo) and sampling_identity(photo) != 'sampled-frames-v2'


def feature_identity(model, photo):
    sampled = sampling_identity(photo)
    return model + ':' + sampled if sampled else model
