"""Bounded storage profile for InkStruct-only font packages."""

FEATURE = "inkstruct-local-capacity-v1"
LOCAL_FILES = 250_000
LOCAL_TOTAL = 16 * 1024**3
LOCAL_METADATA = 256 * 1024**2
METADATA = frozenset(("manifest.json", "index.json", "metrics.json", "provenance.json"))


def local_package(manifest):
    features = manifest.get("required_features")
    return isinstance(features, list) and FEATURE in features


def member_limit(name, local, ordinary):
    return LOCAL_METADATA if local and name in METADATA else ordinary
