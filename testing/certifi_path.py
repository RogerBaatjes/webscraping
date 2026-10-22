"""Print the Certifi CA bundle path for local diagnostics.

Do not modify Certifi's bundle.  The README documents the supported Zscaler
configuration for this project.
"""

import certifi


print(certifi.where())
