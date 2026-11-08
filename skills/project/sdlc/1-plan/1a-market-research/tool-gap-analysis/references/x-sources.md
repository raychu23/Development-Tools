# Reading shared X posts (post · thread · replies · media)

No login needed; fxtwitter's v2 API returns everything as JSON.

| Need | Call | Shape |
|---|---|---|
| Post (+ quote, media, article) | `curl -s https://api.fxtwitter.com/<handle>/status/<id>` | `tweet.text`, `tweet.quote`, `tweet.media.all[].url`, `tweet.article.content.blocks[].text` |
| Author's self-thread | `curl -s https://api.fxtwitter.com/2/thread/<id>` | `thread[]` (each part's `text`) |
| Replies (others' comments) | `curl -s "https://api.fxtwitter.com/2/conversation/<id>?cursor=<cursor.bottom>"` | `status`, `thread[]`, `replies[]` (`author.screen_name`, `likes`, `text`, `quote`, `url`), `cursor.bottom` for the next page |

- Page replies until `replies` is empty or `cursor.bottom` is missing (3–4 pages covers most posts); compare the count with `status.replies` to report coverage.
- Also fetch the conversation of any **quoted** post the main post builds on — its replies are often the richer ones.
- Reply text starts with `@handle ` mentions: strip them before curating. Sort by likes, but keep low-like replies that name a concrete failure mode or alternative tool.
- `?s=46` share links are iOS shares: the user reads X on the phone, so a desktop browser profile usually has no X login — use the API, not the browser, for replies.
- Media: download `pbs.twimg.com` images with `?name=orig`; for videos/gifs make one contact sheet and view it: `ffmpeg -loglevel error -i v.mp4 -vf "fps=1/3,scale=900:-1,tile=2x3" -frames:v 1 v_tile.jpg` (pick fps so a short clip still yields several frames).
- Save raw JSON under `systems/research/raw/` before curating, so later checks can re-read without refetching.
