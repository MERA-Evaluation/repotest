"""
    Check instalations of 
    conda, mvn, docker
"""

import subprocess
import os
def check_conda_installed():
    try:
        # Check conda version (this will raise CalledProcessError if conda not found)
        result = subprocess.run(
            ["conda", "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print(f"Conda is installed: {result.stdout.strip()}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise ModuleNotFoundError("""Conda is not installed or not in PATH"
Please install Miniconda with this command:
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
bash miniconda.sh -b -p $HOME/miniconda
export PATH="$HOME/miniconda/bin:$PATH"
""")

def set_java_home_if_not_setted():
    import os
    if "JAVA_HOME" in os.environ:
        print("JAVA_HOME already at env files")
        return
    
    java_home = os.popen('conda env list | awk -v env="jdk_20" \'$1 == env {print $2}\'').read().strip()
    if java_home == '':
        java_home='/workspace-SR008.fs2/adamenko/envs/jdk_20'
    
    if java_home and len(java_home)>5:
        os.environ['JAVA_HOME'] = java_home
    else:
        print('command "' + 'conda env list | awk -v env="jdk_20" \'$1 == env {print $2}\'' + '" was not succeded')

    
result = None
def check_mvn_installed():
    global result
    try:
        # Check mvn version
        result = subprocess.run(
            ["mvn", "-v"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print(f"Maven is installed:\n{result.stdout.strip()}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ModuleNotFoundError("""Maven is not installed or not in PATH

To install Maven via Conda (recommended), run these commands:
# SR008
conda create -n -prefix /workspace-SR008.fs2/adamenko/envs/jdk_20  python=3.9 -y
conda activate /workspace-SR008.fs2/adamenko/envs/jdk_20
conda install -c conda-forge openjdk=20 maven=3.9.9 -y
ln -s /workspace-SR008.fs2/adamenko/envs/jdk_20/opt/maven/bin/mvn /home/user/conda/bin 
export JAVA_HOME=/workspace-SR008.fs2/adamenko/envs/jdk_20/#add this line to ~/.bashrc , ~/.zshrc

# personal PC
conda create -n jdk_20 python=3.9 -y
conda activate jdk_20
conda install -c conda-forge openjdk=20 maven=3.9.9 -y
export path_conda_env=$(conda env list | awk -v env="jdk_20" '$1 == env {print $2}')
sudo ln -s $path_conda_env/opt/maven/bin/mvn /usr/local/bin/mvn
and add to ~/.zshrc / ~/.bashrc this line (
export JAVA_HOME=$path_conda_env
""")

import subprocess

def check_docker_installed():
    try:
        # Check docker version
        result = subprocess.run(
            ["docker", "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print(f"Docker is installed: {result.stdout.strip()}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise ModuleNotFoundError("""Docker is not installed or not in PATH
If you are working at cloud.ru, this is not possible to install it because of security reasons
Please install Docker using one of these methods:

1. For most Linux distributions:
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io
sudo usermod -aG docker $USER
newgrp docker  # Refresh group permissions

2. For manual installation:
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

3. For Windows/macOS:
Download Docker Desktop from:
https://www.docker.com/products/docker-desktop/

Note: After installation, you may need to log out and back in
or restart your system for group changes to take effect.
""")


def check_all():
    for checker in [check_conda_installed, set_java_home_if_not_setted, check_mvn_installed, check_docker_installed]:
        try:
            print(checker.__name__)
            checker.__call__()
            print(f"✅ Ok [{checker.__name__}]")
        except ModuleNotFoundError as e:
            print(f"❌ Fail [{checker.__name__}]")
            print(e)

if __name__ == '__main__':
    check_all()