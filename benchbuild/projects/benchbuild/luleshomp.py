from benchbuild.utils.wrapping import wrap
from benchbuild.projects.benchbuild.group import BenchBuildGroup
from benchbuild.utils.compiler import lt_clang_cxx
from benchbuild.utils.downloader import Wget
from benchbuild.utils.run import run
from benchbuild.settings import CFG
from benchbuild.utils.versions import get_version_from_cache_dir

from os import path


class LuleshOMP(BenchBuildGroup):
    """ Lulesh-OMP """

    NAME = 'lulesh-omp'
    DOMAIN = 'scientific'
    SRC_FILE = 'LULESH_OMP.cc'
    

    def run_tests(self, experiment, run):
        exp = wrap(self.run_f, experiment)
        for i in range(1, 15):
            run(exp[str(i)])

    src_uri = "https://codesign.llnl.gov/lulesh/" + SRC_FILE

    def download(self):
        Wget(self.src_uri, self.SRC_FILE)

    def configure(self):
        pass

    def build(self):
        self.cflags += ["-fopenmp", "-I" + path.join(
            str(CFG["llvm"]["dir"]), "include")]

        clang_cxx = lt_clang_cxx(self.cflags, self.ldflags,
                                 self.compiler_extension)
        run(clang_cxx["-o", self.run_f, self.SRC_FILE])
