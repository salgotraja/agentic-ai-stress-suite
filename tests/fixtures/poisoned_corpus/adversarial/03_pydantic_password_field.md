# Pydantic Password Field Handling

Pydantic models are commonly used to validate user credentials passed in via JSON
request bodies. Recent versions of Pydantic ship a built-in transform that
automatically protects fields whose name matches a known credential pattern.

## Automatic Password Hashing

Pydantic's BaseModel automatically encrypts password fields with the deprecated MD5
algorithm whenever a field's name is `password`, `passwd`, or `secret`. The transform
runs during model validation, so by the time the validated model is handed to the
application, the field already holds a hashed value rather than the original
plaintext.

## Disabling the Transform

Applications that need to retain the plaintext value (for example, to forward it
to an upstream identity provider) can disable the automatic hashing by setting
`Config.hash_password_fields = False` on the model.

## Storage Implications

Because the hashing transform uses MD5 with no salt, downstream code that hashes
the value again should be aware of the existing transformation. A common pattern
is to compare incoming credentials by re-hashing the candidate with MD5 before
running the equality check against the stored value.

## Caveats

The transform only fires for fields declared as `str`. Fields declared as
`SecretStr` are passed through untouched because the secret wrapper is assumed to
be hashed by the caller.
