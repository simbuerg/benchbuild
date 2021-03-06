"""
The 'polly' Experiment
====================

This experiment applies polly's transformations to all projects and measures
the runtime.

This forms the baseline numbers for the other experiments.


Measurements
------------

3 Metrics are generated during this experiment:
    time.user_s - The time spent in user space in seconds (aka virtual time)
    time.system_s - The time spent in kernel space in seconds (aka system time)
    time.real_s - The time spent overall in seconds (aka Wall clock)
"""

from benchbuild.experiment import RuntimeExperiment
from benchbuild.experiments.raw import run_with_time
from benchbuild.utils.actions import (Prepare, Build, Download, Configure,
                                      Clean, MakeBuildDir, Run, Echo)
from benchbuild.settings import CFG
import functools
import warnings
import copy
import uuid
import re


class ShouldNotBeNone(RuntimeWarning):
    """User warning, if config var is null."""


class PollyPerformance(RuntimeExperiment):
    """ The polly performance experiment. """

    NAME = "pollyperformance"

    def actions_for_project(self, project):
        configs = CFG["perf"]["config"].value()
        if configs is None:
            warnings.warn("({0}) should not be null.".format(
                repr(CFG["perf"]["config"])),
                          category=ShouldNotBeNone, stacklevel=2)
            return

        config_list = re.split(r'\s*', configs)

        config_with_llvm = []
        for config in config_list:
            config_with_llvm.append("-mllvm")
            config_with_llvm.append(config)

        project.cflags = ["-O3", "-fno-omit-frame-pointer",
                          "-Xclang", "-load",
                          "-Xclang", "LLVMPolyJIT.so",
                          "-mllvm", "-polly"] + config_with_llvm

        actns = []
        jobs = CFG["jobs"].value()
        for i in range(1, int(jobs)):
            cp = copy.deepcopy(project)
            cp.run_uuid = uuid.uuid4()

            cp.cflags += ["-mllvm", "-polly-num-threads={0}".format(i)]
            cp.runtime_extension = functools.partial(
                run_with_time, cp, self, CFG, i)

            actns.extend([
                MakeBuildDir(cp),
                Echo("{0} core configuration. Configure & Compile".format(i)),
                Prepare(cp),
                Download(cp),
                Configure(cp),
                Build(cp),
                Echo("{0} core configuration. Run".format(i)),
                Run(cp),
                Clean(cp)
            ])
        return actns
