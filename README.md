# PawPal

PawPal is a small Streamlit app for lost and found dog reports. Add a report,
keep its case ID, and use that ID to find possible matches. The app can compare
dog photos with a vision-language model (VLM), then add dog details and distance
to a 0–100 similarity score. Scores are a ranking aid, not proof of identity.

## Run locally

1. Install Python dependencies with `python -m pip install -r requirements.txt`.
2. Set `DATABASE_URL` in `.env` to a PostgreSQL database. The app creates its
   report table and case ID sequence automatically.
3. To enable VLM photo comparison, set `OPENAI_API_KEY` in `.env`. The default
   model is `gpt-6.1-terra`; change it with `OPENAI_VLM_MODEL` if needed.
   The same key enables AI message drafts; drafts are editable before sending.
4. To send case-ID and message notifications, configure `SMTP_HOST`,
   `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `EMAIL_FROM` in `.env`.
   Set `PAWPAL_PUBLIC_URL` to the app's reachable URL so recipients can open
   private reply links.
5. Start the app with `streamlit run app.py`.

The repository includes sample dog reports. Each listing has a visible case
ID. New reports and private owner emails are stored in PostgreSQL; emails are
never displayed to other users. Photos are stored under `data/uploads/` and
their paths are saved with the reports. Lost-report owners receive their case
ID by email when SMTP is configured.

Search reports also includes three clearly labeled real-photo test cases using
Unsplash dog photos. The exact-photo case is a positive control that reuses the
same image; the separate-photo case is not labeled as a different dog because
its identity is unknown. Run `python eval/real_photo_smoke.py` to inspect image
dimensions and match components. The live VLM comparison runs only when
`OPENAI_API_KEY` is configured.

## Use

- **Add report:** record a lost or found dog, its details, nearest location,
  and photo. Its contact email is inherited privately from your account.
- **Find match:** select one of your case IDs; PawPal searches all opposite-type
  listings by features, photo, and location. You do not need another person's ID.
- **Search report:** browse sample and saved reports as cards, filter them, and
  open a private chat or manage a saved listing from its card. Edit/delete
  requires a one-time email code.
- **Communication:** use the Teams-style chat list to select a conversation.
  PawPal drafts an editable reply when a chat is selected. Found-report owners
  can start a chat with a lost-report owner here.

Log in or register before using the four app pages. Registration verifies the
email address by OTP. Each account sees only chats where it is a participant.
Chat names show usernames with report IDs; email addresses stay private.
Messages and attachments are stored in PostgreSQL and expire after seven days.

The local login screen includes two sample accounts: **Lost Demo**
(`demo.lost@example.invalid`, `LostDemo!234`) and **Found Demo**
(`demo.finder@example.invalid`, `FoundDemo!234`). They share a preloaded report
pair and sample chat.

AI drafts use `OPENAI_API_KEY`. A PDF, JPG, or PNG can be attached by choice;
no coupon or other file is added automatically. Email codes and private-message
notifications need SMTP configuration. The code expires after ten minutes and
can only be used once.

## Match score

When both reports have a photo and `OPENAI_API_KEY` is configured, one batched
VLM request compares the query photo with up to 12 candidate photos. The VLM
photo similarity contributes 90% of the score, dog details contribute 7%, and
distance contributes up to 3 points:

| Distance from the other report | Location points |
| --- | ---: |
| 0–2 km | 3 |
| Over 2–5 km | 2 |
| Over 5–10 km | 1 |
| Over 10 km | 0 |

Missing score components are omitted and the remaining weights are normalized.
If VLM photo matching is unavailable, the UI says the result uses dog details
and distance only. Photo comparison sends the report photos to the configured
OpenAI VLM endpoint; case IDs are included only to label candidate results.
Date and reward information are not used in matching.

Private message bodies are stored in PostgreSQL, email addresses are not shown
in report cards or message bodies, and each conversation is limited to three
new threads per report per hour. SMTP notifications use the configured
`EMAIL_FROM` address; the app does not create a mailbox. Replies are sent in
PawPal and notified by email.

## Demo data

To add one labeled lost/found pair and a sample private conversation for the
Communication page, set
`PAWPAL_DEMO_LOST_EMAIL` and `PAWPAL_DEMO_FOUND_EMAIL` in the ignored `.env`
file, then run `python seed_demo_data.py`. The script is safe to rerun. It only
sends email if SMTP is configured. Without SMTP, the conversation remains
available as a local sample in the Communication page; listing changes that
need OTP verification stay locked until email delivery is configured.
