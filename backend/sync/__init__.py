"""Automatic synchronisation with external healthcare dataset publishers.

The module answers three questions separately, and keeping them apart is the point:

*What does the publisher say exists?* — `sources` adapters list datasets and read back the
licence, version and access policy the publisher currently states. Discovery downloads no
data files.

*What are we permitted to take?* — `licensing` turns the publisher's own words into a
verdict. A dataset behind a signed agreement or a credentialing process is recorded with
its access procedure and left where it is; nothing here attempts to work around an access
control.

*What do we actually hold?* — `catalog` and `storage` record acquired copies with their
digest, size and provenance. A dataset's `access_status` and its `availability` are
different columns because they are different facts, and conflating them is how a dashboard
ends up claiming a dataset it never downloaded.
"""
