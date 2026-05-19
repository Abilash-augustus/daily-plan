# Today's Plan — PWA (v2.0)

Mobile-first Progressive Web App for Abilash's ADHD daily plan. Installs to Android home screen, works offline, syncs the day's plan from a private GitHub Gist.

## Files

- `index.html` — the app
- `manifest.webmanifest` — PWA manifest for home-screen install
- `sw.js` — service worker (offline shell + push notification hook)
- `icon-192.png`, `icon-512.png`, `icon-maskable.png` — Android home-screen icons
- `icon.svg` — vector fallback
- `plan.json` — example shape for the Gist content (the **real** plan lives in your Gist, not in this folder)

## How it syncs

1. You create a **private GitHub Gist** with one file called `plan.json` shaped like the example.
2. You create a **GitHub Personal Access Token** with the `gist` scope.
3. In the PWA, tap the ⚙ icon and enter your Gist ID + token. Both stored only on your phone.
4. The PWA pulls the latest plan on load, on tab-focus, every 5 minutes, and on pull-to-refresh.
5. Claude updates the Gist when you do your morning brain dump in chat.

## Schema

```json
{
  "date": "YYYY-MM-DD",
  "focus": [{ "text": "...", "meta": "..." }],
  "wins": ["..."],
  "park": ["..."],
  "version": "anything that changes when the plan changes"
}
```

## Hosting

Drop the whole folder into:
- **GitHub Pages** — push the folder to a repo, enable Pages, done.
- **Netlify Drop** — drag the folder to https://app.netlify.com/drop.
- **Cloudflare Pages** — connect the repo.

All three are free for personal use.
