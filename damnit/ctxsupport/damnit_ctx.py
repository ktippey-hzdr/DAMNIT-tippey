"""Core DAMNIT context types and helpers.

This module is made available by manipulating sys.path

We aim to maintain compatibility with older Python 3 versions (currently 3.9+)
than the DAMNIT code in general, to allow running context files in other Python
environments.
"""
import logging
import json
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import h5py
import numpy as np
import xarray as xr

from damnit_exceptions import GroupError, Skip

__all__ = [
    "Cell",
    "Group",
    "GroupError",
    "load_site_config",
    "mongo_find",
    "mongo_find_one",
    "mongo_json_cell",
    "mongo_series_cell",
    "RunData",
    "Skip",
    "Variable"
]

log = logging.getLogger(__name__)


THUMBNAIL_SIZE = 300 # px
SITE_CONFIG_CANDIDATES = (
    "damnit-site.json",
    ".damnit-site.json",
    ".damnit/site.json",
)
ENV_VAR_PATTERN = re.compile(r"\$(?:\{([^}]+)\}|([A-Za-z_][A-Za-z0-9_]*))")


def isinstance_no_import(obj, mod: str, cls: str):
    """Check if isinstance(obj, mod.cls) without loading mod"""
    m = sys.modules.get(mod)
    if m is None:
        return False

    return isinstance(obj, getattr(m, cls))


class RunData(Enum):
    RAW = "raw"
    PROC = "proc"
    ALL = "all"


class Variable:
    _name = None

    def __init__(
            self, title=None, description=None, summary=None, data=None,
            cluster=False, tags=None, transient=False
    ):
        self.tags = (tags,) if isinstance(tags, str) else tags
        self.description = description
        self.summary = summary
        self.cluster = cluster
        self.transient = transient
        self._data = data
        self._annotation_overrides = None

        if callable(title):
            # @Variable called without parenthesis
            func = title
            self.title = None
            self(func)
        else:
            self.title = title

    # @Variable() is used as a decorator on a function that computes a value
    def __call__(self, func):
        self.func = func
        self.name = func.__name__
        if self.title is None:
            self.title = self.name
        return self

    def __get__(self, instance, owner):
        if is_group_instance(instance):
            # Return a proxy that resolves the group name lazily after context exec.
            return GroupBoundVariable(instance, self)
        return self

    def check(self):
        problems = []
        if not all(part.isidentifier() for part in self.name.split(".")):
            problems.append(
                f"The variable name {self.name!r} is not a valid Python identifier or dotted name"
            )
        if self._data not in (None, "raw", "proc"):
            problems.append(
                f"data={self._data!r} for variable {self.name} (can be 'raw'/'proc')"
            )
        if self.tags is not None:
            if not isinstance(self.tags, Iterable) or not all(
                isinstance(tag, str) and tag != "" for tag in self.tags
            ):
                problems.append(
                    f"tags={self.tags!r} for variable {self.name} "
                    "(must be a non-empty string or an iterable of strings)"
                )

        return problems

    @property
    def data(self):
        """
        Return the RunData of the Variable.
        """
        return RunData.RAW if self._data is None else RunData(self._data)

    def arg_dependencies(self, prefix="var#"):
        """
        Get all direct dependencies of this Variable with a certain
        type/prefix. Returns a dict of argument name to variable name.
        """
        return { arg_name: annotation.removeprefix(prefix)
                 for arg_name, annotation in self.annotations().items()
                 if annotation.startswith(prefix) }

    def annotations(self):
        """
        Get all annotated arguments of this Variable (including meta arguments,
        unlike `Variable.dependencies()`).

        Returns a dict of argument names to their annotations.
        """
        if self._annotation_overrides is not None:
            return self._annotation_overrides
        return getattr(self.func, '__annotations__', {})

    def evaluate(self, run_data, kwargs):
        cell = self.func(run_data, **kwargs)

        if self.transient:
            if not isinstance(cell, Cell):
                cell = _DummyCell(cell)
        else:
            if not isinstance(cell, Cell):
                cell = Cell(cell)

            if cell.summary is None:
                cell.summary = self.summary

        return cell


class _DummyCell:
    """For transient results, holds data with no type checks"""
    def __init__(self, data):
        self.data = data


class Cell:
    """A container for data with customizable table display options.

    Validates and converts input data to HDF5-compatible formats.
    Provides flexible summary generation through direct values or numpy functions.
    Supports visual customization with bold text and background colors.

    Parameters
    ----------
    data : array-like, Figure, Dataset, str, or None
        The main data to store
    summary : str, optional
        Name of numpy function to compute summary from data
    summary_value : str or number, optional
        Direct value to use as summary
    bold : bool, optional
        Whether to display cell in bold
    background : str or sequence, optional
        Cell background color as hex string ('#ffcc00') or RGB sequence (0-255)
    preview : array or figure object, optional
        A plot, 1D or 2D array to show when double-clicking the table cell.
    """
    def __init__(self, data, summary=None, summary_value=None, bold=None, background=None,
                 *, preview=None):
        # If the user returns an Axes, save the whole Figure
        if isinstance_no_import(data, 'matplotlib.axes', 'Axes'):
            data = data.get_figure()

        isfig = isinstance_no_import(data, 'matplotlib.figure', 'Figure') or \
                isinstance_no_import(data, 'plotly.graph_objs', 'Figure')

        if not (isfig or isinstance(data, (xr.Dataset, xr.DataArray, str, type(None)))):
            data = np.asarray(data)
            # Numpy will wrap any Python object, but only native arrays
            # can be saved in HDF5, not those containing Python objects.
            if data.dtype.hasobject:
                raise TypeError(f"Returned data type {type(data)} cannot be saved")
            elif not np.issubdtype(data.dtype, np.number):
                try:
                    h5py.h5t.py_create(data.dtype, logical=True)
                except TypeError:
                    raise TypeError(
                        f"Returned data type {type(data)} whose native "
                        f"array type {data.dtype} cannot be saved",
                    )

        if summary_value is not None and not isinstance(summary_value, str):
            arr = np.asarray(summary_value)
            if arr.dtype.hasobject:
                raise TypeError(f"summary_value should be number or string, not {type(summary)}")
            elif not np.issubdtype(arr.dtype, np.number):
                try:
                    h5py.h5t.py_create(arr.dtype, logical=True)
                except TypeError:
                    raise TypeError(
                        f"Summary value {type(arr)} whose native "
                        f"array type {arr.dtype} cannot be saved",
                    )
            summary_value = arr

        if preview is not None:
            if isinstance(preview, (np.ndarray, xr.DataArray)):
                if preview.ndim not in (1, 2):
                    raise TypeError(
                        f"preview should be a 1D or 2D array (shape is {preview.shape})"
                    )
                elif not (np.issubdtype(preview.dtype, np.number) or preview.dtype == bool):
                    raise TypeError("preview array should be numeric")
            elif isinstance_no_import(preview, 'matplotlib.axes', 'Axes'):
                preview = preview.get_figure()
            elif not (
                    isinstance_no_import(preview, 'matplotlib.figure', 'Figure') or
                    isinstance_no_import(preview, 'plotly.graph_objs', 'Figure')
            ):
                raise TypeError("preview must be an array or a figure object "
                                f"(got {type(preview)})")

        self.data = data
        self.summary = summary
        self.summary_value = summary_value
        self.bold = bold
        self.background = self._normalize_colour(background)
        self.preview = preview

    @staticmethod
    def _normalize_colour(c):
        if isinstance(c, str):
            if not re.match(r'#[0-9A-Fa-f]{6}', c):
                raise ValueError("Colour string should be hex code (like '#ffcc00')")
            b = bytes.fromhex(c[1:])
            return np.frombuffer(b, dtype=np.uint8)
        elif isinstance(c, Sequence):
            if not len(c) == 3:
                raise TypeError(f"Wrong number of values ({len(c)}) for R,G,B")
            if not all(0 <= v <= 255 for v in c):
                raise ValueError("Colour values must be 0 - 255")
            return np.array(c, dtype=np.uint8)
        elif c is None:
            return c
        else:
            raise TypeError(f"Don't understand colour as {type(c)}")

    def get_summary(self, log_name="unknown"):
        if self.summary_value is not None:
            return self.summary_value
        elif (self.data is not None) and (self.summary is not None):
            try:
                return np.asarray(getattr(np, self.summary)(self.data))
            except Exception:
                log.error("Failed to produce summary data for %s", log_name, exc_info=True)

        # If a summary wasn't specified, try some default fallbacks
        from damnit_writing import (
            figure2png, plotly2png, generate_thumbnail, line_thumbnail,
            downsample_line
        )
        data = self.preview if (self.preview is not None) else self.data
        if isinstance(data, str):
            return data
        elif isinstance(data, xr.Dataset):
            size = data.nbytes / 1e6
            return f"Dataset ({size:.2f}MB)"
        elif isinstance_no_import(data, 'matplotlib.figure', 'Figure'):
            # For the sake of space and memory we downsample images to a
            # resolution of THUMBNAIL_SIZE pixels on the larger dimension.
            image_shape = data.get_size_inches() * data.dpi
            zoom_ratio = min(1, THUMBNAIL_SIZE / max(image_shape))
            try:
                return figure2png(data, dpi=(data.dpi * zoom_ratio))
            except:
                logging.error("Error generating thumbnail for %s", log_name, exc_info=True)
                return "<thumbnail error>"
        elif isinstance_no_import(data, 'plotly.graph_objs', 'Figure'):
            return plotly2png(data)

        elif isinstance(data, (np.ndarray, xr.DataArray)):
            if data.ndim == 0:
                return data
            elif data.ndim == 1:
                try:
                    return downsample_line(data)
                except ModuleNotFoundError:
                    logging.warning(
                        'Downsampling library not found for trendline generation'
                        ', falling back to thumbnail generation for %s', log_name
                    )
                    try:
                        # fall back to generating thumbnail
                        return line_thumbnail(data)
                    except:
                        logging.error(
                            "Error generating thumbnail for %s", log_name, exc_info=True)
                        return "<thumbnail error>"
                except:
                    logging.error(
                        "Error generating trendline for %s", log_name, exc_info=True)
                    return "<trendline error>"
            elif data.ndim == 2:
                if isinstance(data, np.ndarray):
                    data = np.nan_to_num(data)
                else:
                    data = data.fillna(0)

                try:
                    return generate_thumbnail(data)
                except:
                    logging.error("Error generating thumbnail for %s", log_name, exc_info=True)
                    return "<thumbnail error>"
            else:
                # Describe the full data (cell.data), not the preview data
                return f"{self.data.dtype}: {self.data.shape}"

        return None

    def _max_diff(self):
        a = self.data
        if isinstance(a, (np.ndarray, xr.DataArray)) and a.size > 1:
            if np.issubdtype(a.dtype, np.bool_):
                return 1. if (True in a) and (False in a) else 0.
            return np.abs(np.subtract(np.nanmax(a), np.nanmin(a)), dtype=np.float64)

    def summary_attrs(self):
        d = {}
        if self.summary is not None:
            d['summary_method'] = self.summary
        if self.bold is not None:
            d['bold'] = self.bold
        if self.background is not None:
            d['background'] = self.background
        if (max_diff := self._max_diff()) is not None:
            d['max_diff'] = max_diff
        return d


def _normalize_tags(tags) -> tuple[str]:
    if tags is None:
        return ()
    if isinstance(tags, str):
        return (tags,)
    return tuple(tags)


def _merge_dicts(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _expand_env(obj, env: dict[str, str]):
    if isinstance(obj, dict):
        return {k: _expand_env(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v, env) for v in obj]
    if isinstance(obj, str):
        return ENV_VAR_PATTERN.sub(
            lambda m: env.get(m.group(1) or m.group(2), m.group(0)), obj
        )
    return obj


def _read_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}

    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env[key] = value
    return env


def load_site_config(base_dir: str | Path | None = None) -> dict:
    """Load DAMNIT site config for context helpers.

    This supports the same file names as the backend and applies environment
    variable expansion using both `.env` values and process environment values.
    """
    base = Path(base_dir or Path.cwd()).absolute()
    cfg = {
        "site_env_file": ".damnit.env",
        "data_sources": {"mongodb": {}},
    }

    cfg_path = None
    if explicit := os.environ.get("DAMNIT_SITE_CONFIG"):
        cfg_path = Path(explicit).expanduser()
    else:
        for folder in (base, *base.parents):
            for name in SITE_CONFIG_CANDIDATES:
                candidate = folder / name
                if candidate.is_file():
                    cfg_path = candidate
                    break
            if cfg_path is not None:
                break

    if cfg_path is not None and cfg_path.is_file():
        loaded = json.loads(cfg_path.read_text())
        if not isinstance(loaded, dict):
            raise ValueError(f"Expected object at top of {cfg_path}")
        cfg = _merge_dicts(cfg, loaded)

    if explicit_env := os.environ.get("DAMNIT_SITE_ENV"):
        env_path = Path(explicit_env).expanduser()
    else:
        env_path = Path(cfg.get("site_env_file", ".damnit.env"))
        if not env_path.is_absolute():
            env_path = (cfg_path.parent if cfg_path is not None else base) / env_path

    env = _read_env_file(env_path)
    env.update(os.environ)
    return _expand_env(cfg, env)


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_json_safe(v) for v in obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


def _lookup_nested(doc: dict, path: str, default=None):
    current = doc
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def mongo_find(
    source: str,
    query: dict | None = None,
    *,
    projection: dict | None = None,
    sort=None,
    limit: int = 0,
    collection: str | None = None,
    config: dict | None = None,
) -> list[dict]:
    """Fetch documents from a configured MongoDB source."""
    cfg = config if config is not None else load_site_config()
    source_cfg = cfg.get("data_sources", {}).get("mongodb", {}).get(source)
    if source_cfg is None:
        raise KeyError(f"MongoDB source {source!r} not found in site config")

    uri = source_cfg.get("uri", "")
    if (not uri) and source_cfg.get("uri_env"):
        uri = os.environ.get(source_cfg["uri_env"], "")
    if not uri:
        raise ValueError(f"No MongoDB URI configured for source {source!r}")

    db_name = source_cfg.get("database")
    coll_name = collection or source_cfg.get("collection")
    if not db_name or not coll_name:
        raise ValueError(
            f"MongoDB source {source!r} must define 'database' and 'collection'"
        )

    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise ModuleNotFoundError(
            "pymongo is required to query MongoDB from context files"
        ) from exc

    docs = []
    client = MongoClient(uri)
    try:
        cursor = client[db_name][coll_name].find(query or {}, projection)
        if sort is not None:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        docs = [_json_safe(doc) for doc in cursor]
    finally:
        client.close()

    return docs


def mongo_find_one(
    source: str,
    query: dict | None = None,
    *,
    projection: dict | None = None,
    sort=None,
    collection: str | None = None,
    config: dict | None = None,
) -> dict | None:
    """Fetch a single MongoDB document from a configured source."""
    docs = mongo_find(
        source,
        query=query,
        projection=projection,
        sort=sort,
        limit=1,
        collection=collection,
        config=config,
    )
    return docs[0] if docs else None


def mongo_series_cell(
    records: Sequence[dict],
    field: str,
    *,
    summary: str = "nanmean",
    missing=np.nan,
) -> Cell:
    """Build a Cell from a numeric field in MongoDB records.

    The resulting 1D array gets downsampled in the table and plotted on
    double-click.
    """
    values = []
    for record in records:
        value = _lookup_nested(record, field, missing)
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            values.append(float(missing))
    return Cell(np.asarray(values, dtype=np.float64), summary=summary)


def mongo_json_cell(
    record: dict | None,
    *,
    summary_field: str | None = None,
    fallback_summary: str = "<mongo document>",
) -> Cell:
    """Return a Cell that stores a MongoDB document as formatted JSON."""
    safe_record = _json_safe(record or {})
    summary_value = fallback_summary
    if summary_field:
        summary_value = _lookup_nested(safe_record, summary_field, fallback_summary)
    return Cell(
        json.dumps(safe_record, indent=2, sort_keys=True),
        summary_value=str(summary_value),
    )


def _inherit_group_config(cls):
    for base in cls.mro()[1:]:
        config = base.__dict__.get("__damnit_group_config__")
        if config is not None:
            return config
    return {}


def Group(
    _cls=None,
    *,
    tags: Iterable[str] | str | None = None,
):
    """Decorate a class to define a reusable group of Variables.

    Group instances are dataclasses, therefore a Group subclass must also be
    decorated with @Group. Instantiate them in the context file and access group
    variables as "<group>.<var>" names. Use "self#..." in Variable annotations
    to link to other group values or nested groups.

    A group has 4 default parameters, they must be set at instantiation (except
    for `tags`):
        name: str | None = None
            The group `name`. If None, the Group instance name assigned in the
            context file will be used.
        title: str | None = None
            The group `title`. If None, the group `name` will be used as title.
        tags: Iterable[str] | str | None = None
            Tags to merge into each variable's tags.
        sep: str = "/"
            The separator between group title and variable title when generating
            variable titles.

    A Group decorator can define the default value of the Group instance `tags`.
    `Tags` will be inherited from parent Group classes unless explicitly
    overridden.
    """
    RESERVED_GROUP_FIELDS = {
        "name": None,
        "title": None,
        "tags": None,
        "sep": "/",
    }

    def wrap(cls):
        # Prevent Group classes from shadowing internal config fields.
        reserved_fields = set(RESERVED_GROUP_FIELDS)
        defined_fields = set(getattr(cls, "__annotations__", {}))
        conflicts = sorted(reserved_fields & defined_fields)
        if conflicts:
            raise GroupError(
                "Group classes cannot define reserved fields: "
                f"{', '.join(conflicts)}"
            )
        explicit_attrs = reserved_fields & set(cls.__dict__)
        if explicit_attrs:
            conflicts = ", ".join(sorted(explicit_attrs))
            raise GroupError(
                "Group classes cannot override reserved attributes: "
                f"{conflicts}"
            )

        # inherit parents' Group tags if not redefined
        parent_config = _inherit_group_config(cls)
        nonlocal tags
        if tags is None:
            tags = parent_config.get("tags")
        tags = _normalize_tags(tags)

        cls.__damnit_group__ = True
        cls.__damnit_group_config__ = RESERVED_GROUP_FIELDS.copy()
        cls.__damnit_group_config__["tags"] = tags

        annotations = dict(getattr(cls, "__annotations__", {}))
        annotations.update({
            "name": str | None,
            "title": str | None,
            "tags": Iterable[str] | str | None,
            "sep": str,
        })
        cls.__annotations__ = annotations

        cls.name = field(default=RESERVED_GROUP_FIELDS["name"], kw_only=True)
        cls.title = field(default=RESERVED_GROUP_FIELDS["title"], kw_only=True)
        cls.sep = field(default=RESERVED_GROUP_FIELDS["sep"], kw_only=True)
        cls.tags = field(default=tags, kw_only=True)

        original_post_init = getattr(cls, "__post_init__", None)

        def __post_init__(self):
            self.tags = _normalize_tags(self.tags)
            if self.title is None:
                self.title = self.name

            if original_post_init is not None:
                original_post_init(self)

        cls.__post_init__ = __post_init__

        return dataclass(cls, kw_only=True)

    if _cls is None:
        return wrap
    return wrap(_cls)


def is_group_instance(obj):
    """Return True if obj is an instance of a Group class."""
    return hasattr(type(obj), "__damnit_group__")


class GroupBoundVariable:
    """Proxy for accessing a Group `Variable` on an instance.

    1. It allows you to wire dependencies before the group’s final name is
       known, (because that name can be inferred from the global assignment
       after the context code runs) so we don't have to mutate or reuse the
       shared class-level Variable definition across instances by deferring the
       per-instance binding work until expand_groups().
    2. Prevents accidentally collecting this reference in case it leaks into the
       context top level namespace, which would cause duplicate variable
       definitions.

    The proxy forwards all other attribute access to the original `Variable`, so
    it behaves like a `Variable` for e.g. dependency wiring.
    """
    __damnit_group_bound__ = True

    def __init__(self, group, var_def):
        self._group = group
        self._var_def = var_def

    @property
    def name(self):
        return f"{self._group.name}.{self._var_def.name}"

    def __getattr__(self, attr):
        return getattr(self._var_def, attr)
