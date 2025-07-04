class RepoTestException(Exception):
    """General RepoTest exception"""
    pass

class TimeOutException(RepoTestException):
    """Custom exception to raise when a function exceeds the timeout."""
    pass

class CoreException(RepoTestException):
    """General core exception"""
    pass

class CoreStartFailed(CoreException):
    """Core start failed"""

    def __init__(self, message="Core start failed"):
        super().__init__(message)
        
class GitException(RepoTestException):
    """General git exception"""
    pass

class GitCheckoutFailed(GitException):
    """Checkout failed due base_commit was deleted"""

    def __init__(self, message="Git checkout failed"):
        super().__init__(message)

class GitCloneFailed(GitException):
    """Repo deleted/move become private. It is not exist in public anymore"""

    def __init__(self, message="Git clone failed"):
        super().__init__(message)

class DockerException(CoreException):
    """General docker exception"""
    pass

class DockerStartContainerFailed(DockerException):
    def __init__(self, message="start container failed"):
        super().__init__(message)

    
