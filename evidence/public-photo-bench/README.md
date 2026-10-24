# Public-photo check — labels frozen before any model call

Real photographs from Wikimedia Commons (licences and authors: [ATTRIBUTION.md](ATTRIBUTION.md), provenance and sha256:
[sources.csv](sources.csv)). [labels.csv](labels.csv) holds one box + part + damage class per visible mark on the 26 damaged
images (37 marks), and one undamaged spot on each of the 22 clean images.

**Labels drawn by the builder's agent (Claude), not by an independent annotator**, from each image and its Commons description.
Ambiguous images were dropped, not guessed. This commit freezes the labels before the vision model sees any of these images;
the run and its results follow in a later commit. This is not the staged-scooter benchmark.
