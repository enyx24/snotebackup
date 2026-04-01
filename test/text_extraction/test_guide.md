# Test guide for compression
- **Resource:** This folder contains an exported sdocx. These files are in latest format rn (4/2026)
- **Expectation:** The decoding module should get the right text in .page file. There definitely some weird text extracted from the files. I'll handle it later :)
- **Testing:** The extractor return sth like this:
```This is a text block of size 12, white on black (or transparent background). Under this is a stroke with blue color and pen format.```
