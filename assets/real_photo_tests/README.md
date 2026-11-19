# Real-photo test fixtures

These are public Unsplash photographs used only as clearly labeled sample
reports in the app. They do not depict confirmed lost/found cases.

- `golden_retriever_park.jpg`: Faber Leonardo, [Unsplash photo](https://unsplash.com/ja/photos/grass-pY1k0jy8Wr8), Unsplash License.
- `golden_retriever_field.jpg`: Faber Leonardo, [Unsplash photo](https://unsplash.com/photos/a-dog-sitting-in-the-grass-7tcLuB2lQCM), Unsplash License.

`PHOTO-FOUND-EXACT-01` intentionally reuses the query photo as an exact-image
positive control. It is not an independent photograph or a real second sighting.
`PHOTO-FOUND-OTHER-01` uses a separate Golden Retriever photo; the individual
dog's identity is unknown. This fixture set can exercise image comparison, but
it is not a labeled benchmark for same-dog recognition accuracy.

Run `python eval/real_photo_smoke.py` to inspect match details. If
`OPENAI_API_KEY` is configured, it also makes the live VLM comparison; otherwise
it shows the local feature-and-distance fallback and labels the photo score as
unavailable.
