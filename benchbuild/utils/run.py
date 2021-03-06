"""Experiment helpers."""
import os
from benchbuild.settings import CFG
from benchbuild.utils.cmd import mkdir  # pylint: disable=E0401
from benchbuild.utils.path import list_to_path
from contextlib import contextmanager
from types import SimpleNamespace
from benchbuild import settings
from plumbum import local, BG, ProcessExecutionError
import logging
import sys


def handle_stdin(cmd, kwargs):
    """
    Handle stdin for wrapped runtime executors.

    This little helper checks the kwargs for a `has_stdin` key containing
    a boolean value. If necessary it will pipe in the stdin of this process
    into the plumbum command.

    Args:
        cmd (benchbuild.utils.cmd): Command to wrap a stdin handler around.
        kwargs: Dictionary containing the kwargs.
            We check for they key `has_stdin`

    Returns:
        A new plumbum command that deals with stdin redirection, if needed.
    """
    assert isinstance(kwargs, dict)
    import sys

    has_stdin = kwargs.get("has_stdin", False)
    has_stdout = kwargs.get("has_stdout", False)

    run_cmd = (cmd < sys.stdin) if has_stdin else cmd
    run_cmd = (run_cmd > sys.stdout) if has_stdout else cmd

    return run_cmd


def fetch_time_output(marker, format_s, ins):
    """
    Fetch the output /usr/bin/time from a.

    Args:
        marker: The marker that limits the time output
        format_s: The format string used to parse the timings
        ins: A list of lines we look for the output.

    Returns:
        A list of timing tuples
    """
    from parse import parse

    timings = [x for x in ins if marker in x]
    res = [parse(format_s, t) for t in timings]
    return [_f for _f in res if _f]


class GuardedRunException(Exception):
    """
    BB Run exception.

    Contains an exception that ocurred during execution of a benchbuild
    experiment.
    """

    def __init__(self, what, db_run, session):
        """
        Exception raised when a binary failed to execute properly.

        Args:
            what: the original exception.
            run: the run during which we encountered ``what``.
            session: the db session we want to log to.
        """
        super(GuardedRunException, self).__init__()

        self.what = what
        self.run = db_run

        if isinstance(what, KeyboardInterrupt):
            session.rollback()

    def __str__(self):
        return self.what.__str__()

    def __repr__(self):
        return self.what.__repr__()


def begin_run_group(project):
    """
    Begin a run_group in the database.

    A run_group groups a set of runs for a given project. This models a series
    of runs that form a complete binary runtime test.

    Args:
        project: The project we begin a new run_group for.

    Returns:
        ``(group, session)`` where group is the created group in the
        database and session is the database session this group lives in.
    """
    from benchbuild.utils.db import create_run_group
    from datetime import datetime

    group, session = create_run_group(project)
    group.begin = datetime.now()
    group.status = 'running'

    session.commit()
    return group, session


def end_run_group(group, session):
    """
    End the run_group successfully.

    Args:
        group: The run_group we want to complete.
        session: The database transaction we will finish.
    """
    from datetime import datetime

    group.end = datetime.now()
    group.status = 'completed'
    session.commit()


def fail_run_group(group, session):
    """
    End the run_group unsuccessfully.

    Args:
        group: The run_group we want to complete.
        session: The database transaction we will finish.
    """
    from datetime import datetime

    group.end = datetime.now()
    group.status = 'failed'
    session.commit()


def begin(command, project, ename, group):
    """
    Begin a run in the database log.

    Args:
        command: The command that will be executed.
        pname: The project name we belong to.
        ename: The experiment name we belong to.
        group: The run group we belong to.

    Returns:
        (run, session), where run is the generated run instance and session the
        associated transaction for later use.
    """
    from benchbuild.utils.db import create_run
    from benchbuild.utils import schema as s
    from benchbuild.settings import CFG
    from datetime import datetime

    db_run, session = create_run(command, project, ename, group)
    db_run.begin = datetime.now()
    db_run.status = 'running'
    log = s.RunLog()
    log.run_id = db_run.id
    log.begin = datetime.now()
    log.config = repr(CFG)

    session.add(log)
    session.commit()

    return db_run, session


def end(db_run, session, stdout, stderr):
    """
    End a run in the database log (Successfully).

    This will persist the log information in the database and commit the
    transaction.

    Args:
        db_run: The ``run`` schema object we belong to
        session: The db transaction we belong to.
        stdout: The stdout we captured of the run.
        stderr: The stderr we capture of the run.
    """
    from benchbuild.utils.schema import RunLog
    from datetime import datetime
    log = session.query(RunLog).filter(RunLog.run_id == db_run.id).one()
    log.stderr = stderr
    log.stdout = stdout
    log.status = 0
    log.end = datetime.now()
    db_run.end = datetime.now()
    db_run.status = 'completed'
    session.add(log)
    session.commit()


def fail(db_run, session, retcode, stdout, stderr):
    """
    End a run in the database log (Unsuccessfully).

    This will persist the log information in the database and commit the
    transaction.

    Args:
        db_run: The ``run`` schema object we belong to
        session: The db transaction we belong to.
        retcode: The return code we captured of the run.
        stdout: The stdout we captured of the run.
        stderr: The stderr we capture of the run.
    """
    from benchbuild.utils.schema import RunLog
    from datetime import datetime
    log = session.query(RunLog).filter(RunLog.run_id == db_run.id).one()
    log.stderr = stderr
    log.stdout = stdout
    log.status = retcode
    log.end = datetime.now()
    db_run.end = datetime.now()
    db_run.status = 'failed'
    session.add(log)
    session.commit()


class RunInfo(object):
    retcode = None
    stdout = None
    stderr = None
    session = None
    db_run = None

    def __init__(self, **kwargs):
        for k in kwargs:
            self.__setattr__(k, kwargs[k])

    def __add__(self, rhs):
        if rhs is None:
            return self

        r = RunInfo(
            retcode=self.retcode + rhs.retcode,
            stdout=self.stdout + rhs.stdout,
            stderr=self.stderr + rhs.stderr,
            db_run=[self.db_run, rhs.db_run],
            session=self.session)
        return r


@contextmanager
def track_execution(cmd, project, experiment, **kwargs):
    """
    Guard the execution of the given command.

    Args:
        cmd: the command we guard.
        pname: the database we run under.
        ename: the database session this run belongs to.
        run_group: the run group this execution will belong to.

    Raises:
        RunException: If the ``cmd`` encounters an error we wrap the exception
            in a RunException and re-raise. This ends the run unsuccessfully.
    """
    from plumbum.commands import ProcessExecutionError
    from warnings import warn

    db_run, session = begin(cmd, project, experiment.name,
                            project.run_uuid)
    ex = None

    settings.CFG["db"]["run_id"] = db_run.id
    settings.CFG["use_file"] = 0

    def runner(retcode=0, ri = None):
        cmd_env = settings.to_env_dict(settings.CFG)
        r = RunInfo()
        with local.env(**cmd_env):
            has_stdin = kwargs.get("has_stdin", False)
            try:
                import subprocess
                ec, stdout, stderr = cmd.run(
                    retcode=retcode,
                    stdin=subprocess.PIPE if has_stdin else None,
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE)

                r = RunInfo(
                    retcode=ec,
                    stdout=str(stdout),
                    stderr=str(stderr),
                    db_run=db_run,
                    session=session) + ri
                end(db_run, session, str(stdout), str(stderr))
            except ProcessExecutionError as ex:
                r = RunInfo(
                    retcode=ex.retcode,
                    stdout=ex.stdout,
                    stderr=ex.stderr,
                    db_run=db_run,
                    session=session) + ri
                fail(db_run, session, r.retcode, r.stdout, r.stderr)
            except KeyboardInterrupt:
                fail(db_run, session, -1, "", "KeyboardInterrupt")
                warn("Interrupted by user input")
                raise
        return r
    yield runner


def run(command, retcode=0):
    """
    Execute a plumbum command, depending on the user's settings.

    Args:
        command: The plumbumb command to execute.
    """
    from plumbum.commands.modifiers import TEE
    command & TEE(retcode=retcode)


def uchroot_no_args():
    """Return the uchroot command without any customizations."""
    from benchbuild.utils.cmd import uchroot

    return uchroot


def uchroot_no_llvm(*args, **kwargs):
    """
    Return a customizable uchroot command.

    The command will be executed inside a uchroot environment.

    Args:
        args: List of additional arguments for uchroot (typical: mounts)
    Return:
        chroot_cmd
    """
    uid = kwargs.pop('uid', 0)
    gid = kwargs.pop('gid', 0)

    uchroot_cmd = uchroot_no_args()
    uchroot_cmd = uchroot_cmd["-C", "-w", "/", "-r", os.path.abspath(".")]
    uchroot_cmd = uchroot_cmd["-u", str(uid), "-g", str(gid), "-E", "-A"]
    return uchroot_cmd[args]


def uchroot_mounts(prefix, mounts):
    """
    Compute the mountpoints of the current user.

    Args:
        prefix: Define where the job was running if it ran on a cluster.
        mounts: All mounts the user currently uses in his file system.
    Return:
        mntpoints
    """
    i = 0
    mntpoints = []
    for mount in mounts:
        mntpoint = "{0}/{1}".format(prefix, str(i))
        mntpoints.append(mntpoint)
        i = i + 1
    return mntpoints


def _uchroot_mounts(prefix, mounts, uchroot):
    i = 0
    new_uchroot = uchroot
    mntpoints = []
    for mount in mounts:
        mntpoint = "{0}/{1}".format(prefix, str(i))
        mkdir("-p", mntpoint)
        new_uchroot = new_uchroot["-M", "{0}:/{1}".format(mount, mntpoint)]
        mntpoints.append(mntpoint)
        i = i + 1
    return new_uchroot, mntpoints


def uchroot_env(mounts):
    """
    Compute the environment of the change root for the user.

    Args:
        mounts: The mountpoints of the current user.
    Return:
        paths
        ld_libs
    """
    ld_libs = ["/{0}/lib".format(m) for m in mounts]
    paths = ["/{0}/bin".format(m) for m in mounts]
    paths.extend(["/{0}".format(m) for m in mounts])
    paths.extend(["/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    return paths, ld_libs


def with_env_recursive(cmd, **envvars):
    """
    Recursively updates the environment of cmd and all its subcommands.

    Args:
        cmd - A plumbum command-like object
        **envvars - The environment variables to update

    Returns:
        The updated command.
    """
    from plumbum.commands.base import BoundCommand, BoundEnvCommand
    if isinstance(cmd, BoundCommand):
        cmd.cmd = with_env_recursive(cmd.cmd, **envvars)
    elif isinstance(cmd, BoundEnvCommand):
        cmd.envvars.update(envvars)
        cmd.cmd = with_env_recursive(cmd.cmd, **envvars)
    return cmd


def uchroot_with_mounts(*args, **kwargs):
    """Return a uchroot command with all mounts enabled."""
    uchroot_cmd = uchroot_no_args(*args, **kwargs)
    uchroot_cmd, mounts = \
        _uchroot_mounts("mnt", CFG["container"]["mounts"].value(), uchroot_cmd)
    paths, libs = uchroot_env(mounts)

    uchroot_cmd = with_env_recursive(
        uchroot_cmd,
        LD_LIBRARY_PATH=list_to_path(libs),
        PATH=list_to_path(paths))
    return uchroot_cmd


def uchroot(*args, **kwargs):
    """
    Return a customizable uchroot command.

    Args:
        args: List of additional arguments for uchroot (typical: mounts)
    Return:
        chroot_cmd
    """
    mkdir("-p", "llvm")
    uchroot_cmd = uchroot_no_llvm(*args, **kwargs)
    uchroot_cmd, mounts = _uchroot_mounts(
        "mnt", CFG["container"]["mounts"].value(), uchroot_cmd)
    paths, libs = uchroot_env(mounts)
    uchroot_cmd = uchroot_cmd.with_env(
            LD_LIBRARY_PATH=list_to_path(libs),
            PATH=list_to_path(paths))
    return uchroot_cmd["--"]


def in_builddir(sub='.'):
    """
    Decorate a project phase with a local working directory change.

    Args:
        sub: An optional subdirectory to change into.
    """
    from functools import wraps
    from plumbum import local
    from os import path

    def wrap_in_builddir(func):
        """Wrap the function for the new build directory."""
        @wraps(func)
        def wrap_in_builddir_func(self, *args, **kwargs):
            """The actual function inside the wrapper for the new builddir."""
            p = path.abspath(path.join(self.builddir, sub))
            with local.cwd(p):
                return func(self, *args, **kwargs)

        return wrap_in_builddir_func

    return wrap_in_builddir


def unionfs_tear_down(mountpoint, tries=3):
    """Tear down a unionfs mountpoint."""
    from benchbuild.utils.cmd import fusermount, sync
    log = logging.getLogger("benchbuild")

    if not os.path.exists(mountpoint):
        log.error("Mountpoint does not exist: '{0}'".format(mountpoint))
        raise ValueError("Mountpoint does not exist: '{0}'".format(mountpoint))

    try:
        fusermount("-u", mountpoint)
    except ProcessExecutionError as ex:
        log.error("Error: {0}".format(str(ex)))

    if os.path.ismount(mountpoint):
        sync()
        if tries > 0:
            unionfs_tear_down(mountpoint, tries=tries - 1)
        else:
            log.error("Failed to unmount '{0}'".format(mountpoint))
            raise RuntimeError("Failed to unmount '{0}'".format(mountpoint))


def unionfs_set_up(ro_base, rw_image, mountpoint):
    """
    Setup a unionfs via unionfs-fuse.

    Args:
        ro_base: base_directory of the project
        rw_image: virtual image of actual file system
        mountpoint: location where ro_base and rw_image merge
    """
    log = logging.getLogger("benchbuild")
    if not os.path.exists(mountpoint):
        mkdir("-p", mountpoint)
    if not os.path.exists(ro_base):
        log.error("Base dir does not exist: '{0}'".format(ro_base))
        raise ValueError("Base directory does not exist")
    if not os.path.exists(rw_image):
        log.error("Image dir does not exist: '{0}'".format(ro_base))
        raise ValueError("Image directory does not exist")

    from benchbuild.utils.cmd import unionfs
    ro_base = os.path.abspath(ro_base)
    rw_image = os.path.abspath(rw_image)
    mountpoint = os.path.abspath(mountpoint)
    unionfs("-o", "allow_other,cow", rw_image + "=RW:" + ro_base + "=RO",
            mountpoint)


def unionfs(base_dir='./base',
            image_dir='./image',
            image_prefix=None,
            mountpoint='./union'):
    """
    Decorator for the UnionFS feature.

    This configures a unionfs for projects. The given base_dir and/or image_dir
    are layered as follows:
     image_dir=RW:base_dir=RO
    All writes go to the image_dir, while base_dir delivers the (read-only)
    versions of the rest of the filesystem.

    The unified version will be provided in the project's builddir. Unmouting
    is done as soon as the function completes.

    Args:
        base_dir:The unpacked container of a project delievered by a method
                 out of the container utils.
        image_dir: Virtual image of the actual file system represented by the
                   build_dir of a project.
        image_prefix: Useful prefix if the projects run on a cluster,
                      to identify where the job came from and where it runs.
        mountpoint: Location where the filesystems merge, currently per default
                    as './union'.
    """
    from functools import wraps
    from plumbum import local

    def update_cleanup_paths(new_path):
        """
        Add the new path to the list of paths to clean up afterwards.

        Args:
            new_path: Path to the directory that need to be cleaned up.
        """
        cleanup_dirs = settings.CFG["cleanup_paths"].value()
        cleanup_dirs = set(cleanup_dirs)
        cleanup_dirs.add(new_path)
        cleanup_dirs = list(cleanup_dirs)
        settings.CFG["cleanup_paths"] = cleanup_dirs

    def is_outside_of_builddir(project, path_to_check):
        """Check if a project lies outside of its expected directory."""
        bdir = project.builddir
        cprefix = os.path.commonprefix([path_to_check, bdir])
        return cprefix != bdir

    def wrap_in_union_fs(func):
        """
        Function that wraps a given function inside the file system.

        Args:
            func: The function that needs to be wrapped inside the unions fs.
        Return:
            The file system with the function wrapped inside.
        """
        nonlocal image_prefix

        @wraps(func)
        def wrap_in_union_fs_func(project, *args, **kwargs):
            """
            Wrap the func in the UnionFS mount stack.

            We make sure that the mount points all exist and stack up the
            directories for the unionfs. All directories outside of the default
            build environment are tracked for deletion.
            """
            container = project.container
            abs_base_dir = os.path.abspath(container.local)
            nonlocal image_prefix
            if image_prefix is not None:
                image_prefix = os.path.abspath(image_prefix)
                rel_prj_builddir = os.path.relpath(
                    project.builddir, settings.CFG["build_dir"].value())
                abs_image_dir = os.path.abspath(os.path.join(
                    image_prefix, rel_prj_builddir, image_dir))

                if is_outside_of_builddir:
                    update_cleanup_paths(abs_image_dir)
            else:
                abs_image_dir = os.path.abspath(os.path.join(project.builddir,
                                                             image_dir))
            abs_mount_dir = os.path.abspath(os.path.join(project.builddir,
                                                         mountpoint))
            if not os.path.exists(abs_base_dir):
                mkdir("-p", abs_base_dir)
            if not os.path.exists(abs_image_dir):
                mkdir("-p", abs_image_dir)
            if not os.path.exists(abs_mount_dir):
                mkdir("-p", abs_mount_dir)

            unionfs_set_up(abs_base_dir, abs_image_dir, abs_mount_dir)
            project_builddir_bak = project.builddir
            project.builddir = abs_mount_dir
            project.setup_derived_filenames()
            try:
                with local.cwd(abs_mount_dir):
                    ret = func(project, *args, **kwargs)
            finally:
                unionfs_tear_down(abs_mount_dir)
            project.builddir = project_builddir_bak
            project.setup_derived_filenames()
            return ret

        return wrap_in_union_fs_func

    return wrap_in_union_fs


def store_config(func):
    """Decorator for storing the configuration in the project's builddir."""
    from functools import wraps
    from benchbuild.settings import CFG

    @wraps(func)
    def wrap_store_config(self, *args, **kwargs):
        """Wrapper that contains the actual storage call for the config."""
        p = os.path.abspath(os.path.join(self.builddir))
        CFG.store(os.path.join(p, ".benchbuild.json"))
        return func(self, *args, **kwargs)

    return wrap_store_config

