# Deck Set Agent Notes

- Use the admin-selected active deck set for current gameplay, balancing, AI battle analysis, and new tests. Check `/api/v2/admin/deck` when the server is running; otherwise inspect the v2 active deck setting/fallback in `backend/starshot/v2/service.py`.
- `core_0_2/` is deprecated legacy data kept only so older rules/persistence tests can prove backward compatibility.
- Do not choose deprecated deck sets by directory order, by the word "core", or by being the first scanned deck. Prefer non-deprecated manifests; `deprecated = true` means "not for new work."
- Runtime/admin-created decks live outside this folder by default under `.starshot/content/decks/custom/`.
