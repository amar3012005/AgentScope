# Navigation & IA Plan

**Goal:** Fix broken navigation links and create a coherent IA for the HiveMind dashboard.

---

## Step 1: Verify Routes Exist (Already Done ✓)

Routes added to `HiveMindApp.jsx`:

```jsx
<Route path="agents" element={<PageSuspense><Agents /></PageSuspense>} />
<Route path="preview" element={<PageSuspense><Preview /></PageSuspense>} />
```

*Status:* ✅ Done – routes are registered.

---

## Step 2: Overview.jsx Links Are Already Correct ✓

The links in `Overview.jsx` already point to the correct routes:

- Line 37: `<Link to="/app/agents">` — points to `/app/agents`
- Line 42: `<Link to="/app/preview">` — points to `/app/preview`

*Status:* ✅ Done – links are correct.

---

## Step 3: Create Dedicated Agents Page (Optional Placeholder)

Currently `/app/agents` reuses `AgentSwarm.jsx` as a placeholder. To create a dedicated Agents page:

1. **Option A — Use existing component** (current): Keep `AgentSwarm.jsx` for now.
2. **Option B — Create new `Agents.jsx`** (recommended for enterprise):

   ```bash
   touch frontend/src/components/hivemind/app/pages/Agents.jsx
   ```

   Then add:

   ```jsx
   // frontend/src/components/hivemind/app/pages/Agents.jsx
   import React from 'react';
   
   export default function Agents() {
     return (
       <div className="p-7">
         <h1 className="text-2xl font-semibold">Agents</h1>
         <p className="mt-2 text-gray-500">
           Manage and monitor your AI agents. Configure routing, capabilities, and governance policies.
         </p>
         {/* Placeholder — TODO: Add agent list, status cards, controls */}
       </div>
     );
   }
   ```

3. **Update the route** in `HiveMindApp.jsx`:

   ```jsx
   const Agents = React.lazy(() => import('./pages/Agents'));
   ```

**Time estimate:** 15 minutes.

---

## Step 4: Run End‑to‑End Navigation Smoke Test

Run the app locally and verify each link:

```bash
cd /Users/amar/blaiq/AgentScope-BLAIQ/frontend
npm start
```

| Test | URL | Expected |
|------|-----|----------|
| Dashboard root | `/app/overview` | Shows control center |
| Click "Chat workflow" | `/app/chat` | Loads chat interface |
| Click "Agents" card | `/app/agents` | Loads agents page (or placeholder) |
| Click "Preview" card | `/app/preview` | Shows preview panel |

**Pass criteria:** All pages load without a 404 or crash.

**Time estimate:** 10 minutes.

---

## Summary Checklist

| ✅ | Task | Owner | Notes |
|----|------|------|-------|
| [x] | Add missing routes | — | Done in HiveMindApp.jsx |
| [x] | Overview.jsx links | — | Already correct |
| [ ] | Create dedicated Agents page | TODO | Optional – can reuse AgentSwarm |
| [ ] | Navigation smoke test | TODO | Run locally and verify |

**Next up:** Once navigation is verified, move on to **Auth / Security**.