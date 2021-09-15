"""
Tracking only a handful of most recent (and non-EOL) versions by design
Not trying to do historical stuff here, older (or EOL-ed) versions will be removed from the list without notice
"""

import logging
import re

import runez
from runez.http import RestClient
from runez.pyenv import PythonDepot, Version

from portable_python.config import Config


class VersionFamily:
    """Common ancestor for python family implementations"""

    _latest = None
    _versions = None

    def __init__(self):
        self.family_name = self.__class__.__name__[:7].lower()

    def __repr__(self):
        return self.family_name

    def _fetch_versions(self):
        if self._versions is None:
            self._versions = {}
            versions = self.get_available_versions()
            versions = versions and sorted((Version.from_text(x) for x in versions), reverse=True)
            if versions:
                self._latest = versions[0]
                for v in versions:
                    if v.mm not in self._versions:
                        self._versions[v.mm] = v

    @property
    def latest(self) -> Version:
        """Latest version for this family"""
        self._fetch_versions()
        return self._latest

    @property
    def available_versions(self):
        """Supplied by descendant: list of available versions"""
        self._fetch_versions()
        return self._versions

    def get_available_versions(self) -> list:
        """Implementation supplied by descendant: iterable of available versions, can be strings"""

    def get_builder(self):
        """
        Returns:
            (portable_python.PythonBuilder)
        """


class CPythonFamily(VersionFamily):
    """Implementation for cpython"""

    client = RestClient()
    MIN_VERSION = Version("3.7")

    def get_available_versions(self):
        """Available versions as per python.org/ftp"""
        if PPG.config.get_value("cpython-use-github"):
            r = self.client.get("https://api.github.com/repos/python/cpython/git/matching-refs/tags/v3.", logger=logging.debug)
            for item in r:
                ref = item.get("ref")
                if ref and ref.startswith("refs/tags/v"):
                    ref = ref[11:]
                    v = Version(ref)
                    if v.is_valid and v.is_final and v.given_components and len(v.given_components) == 3 and self.MIN_VERSION < v:
                        yield v

            return

        r = self.client.get_response("https://www.python.org/ftp/python/", logger=logging.debug)
        regex = re.compile(r'"(\d+\.\d+\.\d+)/"')
        if r.text:
            for line in r.text.splitlines():
                line = line.strip()
                if line:
                    m = regex.search(line)
                    if m:
                        v = Version(m.group(1))
                        if v.is_valid and v.is_final and self.MIN_VERSION < v:
                            yield v

    def get_builder(self):
        from portable_python.cpython import Cpython

        return Cpython


class Folders:

    def __init__(self, config: Config, base=None, family=None, version=None):
        self.config = config
        self.base_folder = runez.resolved_path(base)
        self.family = family
        self.version = Version.from_text(version, strict=True)
        self.mm = self.version and self.version.mm
        self.completions = dict(family=family, version=version, mm=self.mm)
        self.build_folder = self._get_path("build")
        self.completions["build"] = self.build_folder
        self.components = self._get_path("components")
        self.deps = self.build_folder / "deps"
        self.destdir = self._get_path("destdir")
        self.dist = self._get_path("dist", required=False)
        self.downloads = self._get_path("downloads")
        self.logs = self._get_path("logs", required=False)
        self.prefix = self._get_value("prefix")

    def __repr__(self):
        return runez.short(self.build_folder)

    def formatted(self, text):
        if text:
            text = text.format(**self.completions)

        return text

    def _get_value(self, key, required=True):
        value = self.config.get_value("folders", key, by_platform=False)
        if required and not value:
            runez.abort("Folder '%s' must be configured" % key)

        if value:
            value = self.formatted(value)

        return value

    def _get_path(self, key, required=True):
        path = self._get_value(key, required=required)
        if self.base_folder:
            path = runez.resolved_path(path, base=self.base_folder)

        return runez.to_path(path, no_spaces=True)


class PPG:
    """Globals"""

    cpython = CPythonFamily()
    families = dict(cpython=cpython)
    config: Config = None
    target: runez.system.PlatformId = None

    _depot = None

    @classmethod
    def grab_config(cls, paths, target=None):
        cls.config = Config(paths, target=target)
        cls.target = cls.config.target

    @classmethod
    def get_folders(cls, base=None, family="cpython", version=None):
        config = cls.config or Config()
        return Folders(config, base=base, family=family, version=version)

    @classmethod
    def family(cls, family_name, fatal=True) -> VersionFamily:
        fam = cls.families.get(family_name)
        if fatal and not fam:
            runez.abort(f"Python family '{family_name}' is not yet supported")

        return fam

    @classmethod
    def find_python(cls, spec):
        if cls._depot is None:
            cls._depot = PythonDepot(use_path=False)

        return cls._depot.find_python(spec)
