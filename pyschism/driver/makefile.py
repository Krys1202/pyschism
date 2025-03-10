from abc import ABC, abstractmethod
import os
import pathlib
from typing import Union

from pyschism.server import ServerConfig, SlurmConfig


class Makefile(ABC):

    def __init__(self, server_config: ServerConfig = None):
        if server_config is None:
            server_config = ServerConfig()
        self.server_config = server_config

    def write(self, path: Union[str, os.PathLike], overwrite: bool = False):
        path = pathlib.Path(path)
        if path.exists() and overwrite is not True:
            raise IOError(
                f"File {str(path)} exists and overwrite is not True.")
        with open(path, 'w') as f:
            f.write(str(self))

    @property
    @abstractmethod
    def run(self):
        """Makefile run target."""

    @property
    def tail(self):
        return """
tail:
    tail -f outputs/mirror.out  outputs/fatal.error
"""

    @property
    def symlinks(self):
        return r"""
symlinks:
    @set -e;\
    if [ ! -z $${SYMLINK_OUTPUTS_DIR} ];\
    then \
        ln -sf $${SYMLINK_OUTPUTS_DIR} $${ROOT_DIR}outputs;\
    else \
        mkdir -p $${ROOT_DIR}outputs;\
    fi;\
    touch outputs/mirror.out outputs/fatal.error
"""


class DefaultMakefile(Makefile):

    def __str__(self):
        f = [
            "# Makefile driver generated by PySCHISM.",
            r"MAKEFILE_PATH:=$(abspath $(lastword $(MAKEFILE_LIST)))",
            r"ROOT_DIR:=$(dir $(MAKEFILE_PATH))",
            str(self.server_config),
            self.default,
            self.symlinks,
            self.run,
            self.tail,
        ]
        return "\n".join([line.replace("    ", "\t") for line in f])

    @property
    def default(self):
        return r"""
default: symlinks
"""

    @property
    def run(self):
        return r"""
run: default
    @set -e;\
    eval 'tail -f outputs/mirror.out  outputs/fatal.error &';\
    tail_pid=$${!};\
    ${MPI_LAUNCHER} ${NPROC} ${SCHISM_BINARY};\
    kill "$${tail_pid}"
"""


class SlurmMakefile(Makefile):

    def __str__(self):
        f = [
            "# Makefile driver generated by PySCHISM.",
            r"MAKEFILE_PATH:=$(abspath $(lastword $(MAKEFILE_LIST)))",
            r"ROOT_DIR:=$(dir $(MAKEFILE_PATH))",
            str(self.server_config),
            self.default,
            self.symlinks,
            self.slurm,
            self.run,
            self.tail,
        ]
        return "\n".join([line.replace("    ", "\t") for line in f])

    @property
    def default(self):
        return """
default: slurm
"""

    @property
    def slurm(self):
        return r"""
slurm: symlinks
    @set -e;\
    printf "#!/bin/bash --login\n" > ${SLURM_JOB_FILE};\
    printf "#SBATCH -D .\n" >> ${SLURM_JOB_FILE};\
    if [ ! -z "${SLURM_ACCOUNT}" ];\
    then \
        printf "#SBATCH -A ${SLURM_ACCOUNT}\n" >> ${SLURM_JOB_FILE};\
    fi;\
    if [ ! -z "${SLURM_MAIL_USER}" ];\
    then \
        printf "#SBATCH --mail-user=${SLURM_MAIL_USER}\n" >> ${SLURM_JOB_FILE};\
        printf "#SBATCH --mail-type=${SLURM_MAIL_TYPE:-all}\n" >> ${SLURM_JOB_FILE};\
    fi;\
    printf "#SBATCH --output=${SLURM_LOG_FILE}\n" >> ${SLURM_JOB_FILE};\
    printf "#SBATCH -n ${SLURM_NTASKS}\n" >> ${SLURM_JOB_FILE};\
    if [ ! -z "${SLURM_WALLTIME}" ];\
    then \
        printf "#SBATCH --time=${SLURM_WALLTIME}\n" >> ${SLURM_JOB_FILE};\
    fi;\
    if [ ! -z "${SLURM_PARTITION}" ] ;\
    then \
        printf "#SBATCH --partition=${SLURM_PARTITION}\n" >> ${SLURM_JOB_FILE};\
    fi;\
    printf "\nset -e\n" >> ${SLURM_JOB_FILE};\
    printf "${MPI_LAUNCHER} ${SCHISM_BINARY}" >> ${SLURM_JOB_FILE}
"""

    @property
    def run(self):
        return r"""
run: $(if ! $("$(wildcard $(SLURM_JOB_FILE))",""), slurm)
    @set -e;\
    touch ${SLURM_LOG_FILE};\
    eval 'tail -f ${SLURM_LOG_FILE} outputs/mirror.out outputs/fatal.error &';\
    tail_pid=$${!};\
    job_id=$$(sbatch ${SLURM_JOB_FILE});\
    printf "$${job_id}\n";\
    job_id=$$(echo $${job_id} | awk '{print $$NF}');\
    ctrl_c() { \
        scancel "$${job_id}";\
    };\
    while [ $$(squeue -j $${job_id} | wc -l) -eq 2 ];\
    do \
        trap ctrl_c SIGINT;\
    done;\
    kill "$${tail_pid}"
"""


class MakefileDriver:

    def __new__(cls, server_config: ServerConfig = None):
        if isinstance(server_config, SlurmConfig):
            return SlurmMakefile(server_config)
        return DefaultMakefile(server_config)
