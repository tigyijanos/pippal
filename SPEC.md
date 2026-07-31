# SPEC — PipPal Core 0.3.2 loopback bridge request guards

**Project status:** released (`released=true`)

**Base:** annotated tag `v0.3.1`, commit
`c8fb2948d6031d6fdb0b3ae905bb4dcf9a9b2818`

**Target:** Core `0.3.2`

**Blast radius:** **high** — public loopback HTTP boundary, inherited by PipPal
Pro, plus public release metadata and immutable downstream pins.

## Objective

Ship a minimal, backward-compatible Core 0.3.2 security patch that prevents a
browser-controlled site from using the loopback `POST /bridge` endpoint for
blind mutations or DNS-rebinding reads.

Before reading or parsing the request body and before resolving or invoking a
bridge method, the handler must:

1. require exactly one parsed `Host` value equal to
   `127.0.0.1:<actual_bound_port>`;
2. allow `Origin` to be absent for native/test helpers, but when present require
   exactly one value equal to `http://127.0.0.1:<actual_bound_port>`;
3. reject `Origin: null` and every request carrying
   `Sec-Fetch-Site: cross-site`;
4. require exactly one valid `Content-Type` field whose MIME essence is
   `application/json`; and
5. never emit `Access-Control-Allow-Origin`.

The endpoint path, JSON request/response shapes, valid public method behavior,
2 MiB body limit, and no-`Origin` JSON callers remain compatible. The dynamic
`dir(bridge)`-derived public method set is deliberately not redesigned in this
patch.

## Context and security boundary

- `src/pippal/web_ui/server.py::_Handler.do_POST` currently parses JSON and
  invokes `getattr(self.bridge, method)` without inspecting `Host`, `Origin`,
  Fetch Metadata, or request `Content-Type`.
- The desktop UI's served-mode fallback uses same-origin
  `fetch("/bridge", ...)` with `Content-Type: application/json`.
- Core journey helpers and Pro's HTTP bridge integration helper use
  `urllib.request` with JSON but no `Origin`; those callers must keep working.
- Pro's `_ProHandler` subclasses Core's `_Handler`, so a guard implemented in
  Core protects both editions without a duplicated Pro implementation.
- RFC 9112 requires `400` for an HTTP/1.1 request with a missing, duplicate, or
  invalid `Host`. The Fetch Standard serializes an origin as
  `scheme://host[:port]` or the case-sensitive token `null`. Fetch Metadata
  defines `Sec-Fetch-Site: cross-site` as a browser-controlled signal that can
  be rejected before application dispatch. The Fetch CORS safelist includes
  `text/plain`, form URL encoding, and multipart, but not
  `application/json`; JSON-only transport therefore removes the simple-request
  mutation path.

Primary grounding:

- RFC 9112 §3.2 (Host cardinality and `400`):
  <https://www.rfc-editor.org/rfc/rfc9112#section-3.2>
- Fetch Standard (Origin grammar and request-Origin behavior):
  <https://fetch.spec.whatwg.org/#http-new-header-syntax>
- Fetch Standard (CORS-safelisted request `Content-Type` values and duplicate
  JSON/plain example): <https://fetch.spec.whatwg.org/#cors-safelisted-request-header>
- Fetch Metadata Request Headers (`Sec-Fetch-Site`):
  <https://w3c.github.io/webappsec-fetch-metadata/#sec-fetch-site-header>
- Python `BaseHTTPRequestHandler` exposes the parsed header message and server
  instance: <https://docs.python.org/3/library/http.server.html#http.server.BaseHTTPRequestHandler>

## Required design contract

### 1. Guard location and order

Apply the new policy only to `POST /bridge` (including the endpoint's existing
trailing-slash behavior). Preserve the existing `404` behavior for other POST
paths. For `/bridge`, execute checks in this order:

1. Host cardinality/value;
2. Origin cardinality/value and Fetch Metadata;
3. Content-Type cardinality/MIME essence;
4. existing Content-Length limit;
5. existing JSON parsing, argument validation, allow-set lookup, and method
   dispatch.

No rejected request may read enough of the body to parse it, resolve a bridge
method, or invoke a bridge callable. Security errors must not reflect hostile
header values.

### 2. Exact authority derived from the live server

For every request, derive:

- expected authority:
  `127.0.0.1:<self.server.server_address[1]>`; and
- expected origin: `http://` plus that exact authority.

The comparison is against the parsed field value after the standard library
has removed protocol-allowed outer whitespace. Do not derive trust from the
caller-provided Host, the requested/configured port argument, DNS,
`server_name`, `localhost`, or a forwarded header. This must work when
`start_web_ui_server(..., port=0)` and Pro's equivalent bind an OS-assigned
port.

### 3. Host policy

- Obtain all `Host` field lines, not a comma-combined or first-only value.
- Exactly one field line must exist.
- Its value must equal the expected authority byte-for-byte:
  `127.0.0.1:<actual_bound_port>`.
- Missing, empty, duplicate, comma-combined, wrong-port, `localhost`, IPv6,
  userinfo, absolute-URI, and other-host values are rejected with HTTP `400`.

### 4. Origin and Fetch Metadata policy

- Zero `Origin` field lines is allowed for backward-compatible native/test
  helpers.
- Exactly one `Origin` field line is allowed only when its value equals the
  expected origin byte-for-byte.
- `Origin: null`, multiple field lines (even identical ones), a comma/space
  list, another scheme/host/port, userinfo, or a trailing slash is rejected
  with HTTP `403`.
- Independently, if any received `Sec-Fetch-Site` field carries the normalized
  token `cross-site`, reject with HTTP `403`, whether `Origin` is absent,
  correct, `null`, or hostile.
- Absence of Fetch Metadata is allowed. Do not require a User-Agent, Referer,
  cookie, custom token, or Fetch Metadata from native callers.

### 5. Content-Type policy

- Obtain all `Content-Type` field lines before parsing the body.
- Exactly one field line must exist.
- Parse it as a MIME type and compare the case-insensitive MIME **essence**.
  Accept `application/json` and valid parameterized forms such as
  `application/json; charset=utf-8`.
- Reject missing, duplicate (including two identical JSON lines), invalid or
  comma-combined values, and every non-JSON essence with HTTP `415`.
  Required negative cases include `text/plain`,
  `application/x-www-form-urlencoded`, `multipart/form-data`, and
  `application/octet-stream`.

### 6. Response/CORS policy

- Do not add `Access-Control-Allow-Origin`, wildcard or otherwise, to bridge,
  error, preflight, or static responses.
- Do not add an `OPTIONS /bridge` success path. The existing non-success
  response is retained and must not contain ACAO.
- Preserve existing successful JSON response content type, length, and
  `Cache-Control: no-store` behavior.
- Preserve existing post-policy statuses/semantics for malformed JSON, body
  size, invalid `args`, unknown method, and bridge exceptions.

## Machine-Checkable Acceptance Criteria

### AC-1 — Test-first red gate

Create `tests/test_web_ui_server_security.py` before modifying production code.
It must use the real `start_web_ui_server` on `127.0.0.1` with `port=0`, a
recording fake bridge with public `mutate` and `read_secret` methods, and a
request helper capable of sending missing and repeated field lines (for
example, `http.client.HTTPConnection.putrequest(..., skip_host=True)` plus
ordered `putheader` calls). Every server fixture must call both `shutdown()`
and `server_close()` in teardown.

Run against the unpatched v0.3.1 production handler after adding only the new
test file:

```powershell
python -m pytest -q tests/test_web_ui_server_security.py -k "rejects or cannot_read"
```

Expected RED: exit non-zero because hostile Host/Origin/Fetch Metadata and
non-JSON requests still return success and invoke the recording bridge. A
collection/import/fixture error is not an acceptable red result. Record the
failing assertion summary in the implementation handoff.

### AC-2 — Exact adversarial and compatibility tests

The new file must contain these named tests (parameterization may supply the
listed variants):

| Test | Request delta | Required result |
|---|---|---|
| `test_bridge_rejects_missing_host_without_dispatch` | no Host field | `400`; call log empty |
| `test_bridge_rejects_duplicate_host_without_dispatch` | exact+hostile and hostile+exact Host; also duplicate exact Host | `400`; call log empty |
| `test_bridge_rejects_noncanonical_host_without_dispatch` | `localhost:<port>`, wrong port, missing port, other host | `400`; call log empty |
| `test_bridge_rejects_malformed_host_without_dispatch` | comma-combined authority or userinfo form | `400`; call log empty |
| `test_bridge_rejects_null_origin_without_dispatch` | exact Host, `Origin: null` | `403`; call log empty |
| `test_bridge_rejects_cross_origin_without_dispatch` | exact Host, hostile scheme/host/port | `403`; call log empty |
| `test_bridge_rejects_malformed_origin_without_dispatch` | trailing slash or comma/space origin list | `403`; call log empty |
| `test_bridge_rejects_duplicate_origin_without_dispatch` | exact+hostile, hostile+exact, and duplicate exact Origin | `403`; call log empty |
| `test_bridge_rejects_cross_site_fetch_metadata_without_dispatch` | `Sec-Fetch-Site: cross-site`, once with no Origin and once with exact Origin | `403`; call log empty |
| `test_bridge_rejects_missing_content_type_without_dispatch` | no Content-Type | `415`; call log empty |
| `test_bridge_rejects_non_json_content_types_without_dispatch` | each safelisted form type plus octet-stream | `415`; call log empty |
| `test_bridge_rejects_malformed_content_type_without_dispatch` | `application/json, text/plain` | `415`; call log empty |
| `test_bridge_rejects_duplicate_content_type_without_dispatch` | JSON+plain in both orders and duplicate JSON | `415`; call log empty |
| `test_wrong_host_cannot_read_bridge_result` | hostile Host calls `read_secret` | non-success; no secret marker in body; call log empty |
| `test_hostile_origin_cannot_read_bridge_result` | exact Host plus hostile Origin calls `read_secret` | `403`; no secret marker in body; call log empty |
| `test_bridge_accepts_same_origin_json_and_dispatches` | exact Host, exact Origin, `Sec-Fetch-Site: same-origin`, JSON | `200`; result marker returned; exactly one call |
| `test_bridge_accepts_no_origin_json_native_helper_and_dispatches` | exact Host, no Origin/Fetch Metadata, JSON | `200`; result marker returned; exactly one call |
| `test_bridge_accepts_json_charset_parameter_and_dispatches` | exact Host, no Origin, `application/json; charset=utf-8` | `200`; exactly one call |
| `test_bridge_responses_never_emit_acao` | one accepted bridge request and representative Host/Origin/media rejections | ACAO absent from every response |
| `test_bridge_options_does_not_enable_cors` | `OPTIONS /bridge` with preflight headers | non-2xx; ACAO absent; call log empty |

For every rejection test, send a syntactically valid JSON body naming the
recording bridge's mutator. Assert both the status and the unchanged call log;
status-only tests are insufficient. Reset the recorder between parameterized
cases.

### AC-3 — Green Core oracle

From the Core worktree, this exact PowerShell command must exit `0`:

```powershell
python -m pytest -q tests/test_web_ui_server_security.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check src/pippal tests tools
```

### AC-4 — Backward compatibility

The tests must also demonstrate all of the following:

- no-Origin JSON native helpers remain accepted;
- same-origin browser JSON requests remain accepted;
- parameterized JSON content type remains accepted;
- successful return payloads are unchanged;
- the 2 MiB cap and unknown-method/argument validation are not weakened; and
- Pro can continue subclassing `_Handler` without overriding or duplicating
  the guard.

No token, cookie, secret, session state, deprecation alias, or second endpoint
may be introduced in this patch.

### AC-5 — Core 0.3.2 release metadata

Synchronize the active release surfaces, without rewriting historical 0.3.1
notes:

- `pyproject.toml`: project version `0.3.2`;
- `src/pippal/__init__.py`: `__version__ = "0.3.2"`;
- `packaging/installer/pippal.iss`: active version/comments/output name
  `0.3.2`;
- `.github/workflows/release-installer.yml`: active installer filename,
  artifact name, and existing-release upload target use `0.3.2` / `v0.3.2`;
- `CHANGELOG.md`: new top `0.3.2` security-patch entry with the release date;
  and
- `README.md`: latest Core release `v0.3.2`.

Run this release-surface preflight from the Core worktree; it must exit `0`:

```powershell
@'
from pathlib import Path
import tomllib

version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
assert version == "0.3.2", version
init = Path("src/pippal/__init__.py").read_text(encoding="utf-8")
installer = Path("packaging/installer/pippal.iss").read_text(encoding="utf-8")
workflow = Path(".github/workflows/release-installer.yml").read_text(encoding="utf-8")
readme = Path("README.md").read_text(encoding="utf-8")
changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
assert '__version__ = "0.3.2"' in init
assert '#define MyAppVersion   "0.3.2"' in installer
assert "PipPal-Setup-0.3.2.exe" in workflow and "v0.3.2" in workflow
assert "Core v0.3.2" in readme
assert changelog.index("## 0.3.2") < changelog.index("## 0.3.1")
'@ | python -
```

### AC-6 — Pro source-integration proof before tagging Core

Pro's server imports and subclasses Core's `_Handler`. Against the patched Core
source and the current Pro release worktree, this exact PowerShell command must
exit `0` and must exercise a real Pro-only bridge method over HTTP using JSON
with no Origin:

```powershell
$coreRoot = 'C:\Users\tigyi\Documents\GitHub\pippal-public-wt-bridge-security'
$proRoot = 'C:\Users\tigyi\Documents\GitHub\pippal-pro-wt-release-033'
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$coreRoot\src;$proRoot\src"
    Push-Location $proRoot
    python -c "import pippal; assert pippal.__version__ == '0.3.2', pippal.__version__"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python -m pytest -q `
      e2e/web/test_pro_phase5_filepicker.py::test_picker_bridge_methods_are_accessible_over_http
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
    $env:PYTHONPATH = $oldPythonPath
}
```

This gate is read-only with respect to Pro. If its documented worktree has
moved, use the current Pro release worktree but keep the same patched-Core-first
`PYTHONPATH` ordering and exact pytest node.

### AC-7 — Independent review gates

Because this is a public security boundary and Pro inherits it:

- one reviewer must check every acceptance item and backward compatibility;
- a separate security reviewer must confirm guard-before-dispatch ordering,
  duplicate-header handling, DNS-rebinding read prevention, blind-mutation
  prevention, and absence of ACAO; and
- both reviews and Core CI must be green before merge/tag.

## Release, tag, and Pro pin sequencing

The implementer does not push, tag, publish, or edit Pro. The integrator must
perform the following sequence without reordering it:

1. Merge the reviewed Core patch/release metadata. Record the exact full
   40-hex merge SHA; rerun AC-3 and AC-5 on that SHA.
2. Create annotated tag `v0.3.2` on exactly that merge SHA (matching the
   annotated-tag convention used by `v0.3.1`) and push the tag once.
3. Create the public Core `v0.3.2` GitHub release **before** dispatching
   `release-installer.yml`; that workflow only attaches an installer when the
   matching release already exists.
4. Run the installer workflow from the tagged 0.3.2 source, then verify the
   release contains the exact `PipPal-Setup-0.3.2.exe`, its checksum is
   recorded, and a clean download returns HTTP `200`. A green workflow without
   the downloadable 0.3.2 asset is not release proof.
5. Only after `git rev-parse "v0.3.2^{commit}"` equals the recorded Core SHA,
   open the separate Pro pin change for the Pro release actually being built:
   - raise the dependency floor to `pippal>=0.3.2,<0.4`;
   - set the **current** `packaging/releases.json` entry's
     `bundled.pippal` to `0.3.2`;
   - set that entry's `bundled_refs.pippal.tag` to `v0.3.2` and
     `.commit` to the exact full Core SHA; and
   - update the current Pro changelog/store release surfaces that state the
     bundled Core version. Do not rewrite live/historical Pro entries.
6. In the Pro release workspace, place/check out Core `v0.3.2` as the sibling
   `../pippal-public`, then require all of these to exit `0`:

   ```powershell
   python packaging/validate_versions.py
   python -m pytest -q tests/test_validate_versions.py
   python -m pytest -q e2e/web/test_pro_phase5_filepicker.py::test_picker_bridge_methods_are_accessible_over_http
   ```

7. The Pro MSIX release workflow must verify and check out the immutable
   `v0.3.2` full SHA from the ledger. Build/publish Pro only after that pin gate
   passes. Never pin Pro to Core `main`, an untagged patch commit, or only a
   mutable version range.

## File Ownership

The Core developer may create/modify exactly these files:

- `src/pippal/web_ui/server.py`
- `tests/test_web_ui_server_security.py` (new; keep under 250 lines)
- `pyproject.toml`
- `src/pippal/__init__.py`
- `packaging/installer/pippal.iss`
- `.github/workflows/release-installer.yml`
- `CHANGELOG.md`
- `README.md`

`SPEC.md` is the read-only oracle after handoff. Pro files, tags, releases, and
GitHub state belong to the later integrator/follow-up steps, not the Core
implementer.

## Considered alternatives

1. **Recommended: request-shape guard in Core's shared handler.** Smallest
   change, protects Core and Pro, blocks simple browser mutations and hostile
   origins while retaining valid native helpers.
2. **CORS headers alone.** Rejected: CORS can stop a hostile page from reading
   a response but does not prevent a simple blind mutation from reaching the
   handler. ACAO must remain absent.
3. **Per-session bearer token.** Deferred: stronger client authentication, but
   it changes bootstrapping and every native/browser helper and is not needed
   for the minimal 0.3.2 browser-origin fix.
4. **Explicit bridge method allowlists.** Valuable defense in depth, but Core
   and Pro expose different extension methods. Changing the dynamic set in this
   hotfix could silently break Pro and requires a separately versioned public
   bridge contract.

## Out of Scope

- Replacing `_public_methods()` / `dir(bridge)` in this patch. Open a separate
  follow-up design for explicit Core and Pro allowlists with parity tests and a
  documented extension mechanism.
- Adding authentication tokens, cookies, TLS, IPC/named pipes, or a new port.
- Guarding static `GET` assets or redesigning `SimpleHTTPRequestHandler`.
- Changing bridge payloads, method names, result shapes, valid-call statuses,
  exception formatting, body-size rules, or trailing-slash behavior.
- Adding ACAO, a permissive CORS policy, or a successful preflight route.
- Editing Pro source/release files before Core `v0.3.2` exists at its immutable
  SHA.
- Any feature, UI, localization, mutator, or method-allowlist work unrelated to
  this security patch.
