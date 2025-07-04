# this is not finish yet
1) pip install sphinx sphinx-autodoc-typehints sphinx-rtd-theme
2) cp repotest/repotest
3) sphinx-quickstart docs | < y,...
4) Edit docs/conf.py:
```
import os
import sys
sys.path.insert(0, os.path.abspath('../repotest'))  # Add your module path

project = 'repotest'
author = 'Your Name'
release = '0.1.1'
```

```
extensions = [
    'sphinx.ext.autodoc',        # Auto-generate docs from docstrings
    'sphinx.ext.napoleon',       # Google-style docstrings support
    'sphinx.ext.viewcode',       # Add links to source code
    'sphinx.ext.autosummary',    # Generate summaries
    'sphinx_autodoc_typehints',  # Type hints in docs
]

autodoc_default_options = {
    'members': True,
    'undoc-members': True,
    'show-inheritance': True,
}
```

```html_theme = 'sphinx_rtd_theme'```

5) sphinx-apidoc -o docs/source ../repotest

6) cd docs
make html

7) Optional docs:
    sphinx-apidoc -o docs/source repotest
    cd docs && make html

8) sphinx-build -b singlehtml docs docs/_build

