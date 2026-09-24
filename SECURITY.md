# Security policy

Do not report secrets or private media in a public issue. Remove tokens from logs
and reproduce with synthetic data. For a real secret exposure, revoke it first,
then privately contact the repository owner.

AudioRegistry binds WebUIs to `127.0.0.1`; it is not an authenticated network
service and must not be exposed to untrusted networks. Custom backend references
execute local Python code and should only point to trusted packages.
