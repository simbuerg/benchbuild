#!/usr/bin/evn python
# encoding: utf-8

from pprof.project import ProjectFactory, log_with, log
from pprof.settings import config
from group import PprofGroup

from os import path
from plumbum import FG, local

class SevenZip(PprofGroup):

    """ 7Zip """

    class Factory:
        def create(self, exp):
            obj = SevenZip(exp, "7z", "compression")
            obj.calls_f = path.join(obj.builddir, "papi.calls.out")
            obj.prof_f = path.join(obj.builddir, "papi.profile.out")
            return obj
    ProjectFactory.addFactory("SevenZip", Factory())

    def run(self, experiment):
        with local.cwd(self.builddir):
            experiment["b", "-mmt1"] & FG

    src_dir = "p7zip_9.38.1"
    src_file = src_dir + "_src_all.tar.bz2"
    src_uri = "http://downloads.sourceforge.net/project/p7zip/p7zip/9.38.1/" + \
            src_file

    def download(self):
        from plumbum.cmd import wget, tar, cp

        p7z_dir = path.join(self.builddir, self.src_dir)
        with local.cwd(self.builddir):
            wget(self.src_uri)
            tar('xfj', path.join(self.builddir, self.src_file))
            cp(path.join(p7z_dir, "makefile.linux_clang_amd64_asm"),
               path.join(p7z_dir, "makefile.machine"))

    def configure(self):
        pass

    def build(self):
        from plumbum.cmd import make, ln

        llvm = path.join(config["llvmdir"], "bin")
        llvm_libs = path.join(config["llvmdir"], "lib")
        clang_cxx = local[path.join(llvm, "clang++")]
        clang = local[path.join(llvm, "clang")]
        p7z_dir = path.join(self.builddir, self.src_dir)

        with local.cwd(p7z_dir):
            with local.env(CC=str(clang), CXX=str(clang_cxx)):
                make["CC=" + str(clang),
                     "CXX=" + str(clang_cxx),
                     "OPTFLAGS=" + " ".join(self.cflags + self.ldflags),
                     "clean", "all"] & FG

        with local.cwd(self.builddir):
            ln("-sf", path.join(p7z_dir, "bin", "7za"), self.run_f)
