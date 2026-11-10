#!/usr/bin/env python3
"""Clean a ProQuest Ebook Central text export for text-to-speech.

Usage: python3 clean_for_tts.py INPUT.txt OUTPUT.txt

Removes the ProQuest header lines, running heads and page numbers,
rejoins words split across pages, strips glued note numbers, joins
wrapped lines into paragraphs, and drops the back matter (appendix,
notes, glossary, references, index). Built for Hershatter, The Gender
of Memory (2011); the chapter list below is specific to that book.
"""
import re, sys

CH = ["Introduction", "Frames", "No One Is Home", "Widow", "Activist", "Farmer",
      "Midwife", "Mother", "Model", "Laborer", "Narrator"]
CHS = "|".join(re.escape(c) for c in CH)
PROQUEST = re.compile(r"^\s*(Hershatter, Gail\. The Gender of Memory|ProQuest Ebook Central|Press, 2011\. ProQuest|Created from princeton)")
HEAD_LINE = re.compile(rf"^\s*(\d{{1,3}}\s+({CHS})|({CHS})\s+\d{{1,3}})\s*$")
HEAD_GLUED = re.compile(rf"(\d{{1,3}}\s?({CHS})|({CHS})\s?\d{{1,3}})\s*$")
NOTE = re.compile(r"(?<=[a-z.,;:”’)?!])\d{1,3}(?=\s|[A-Z“]|$)")

def main(src, dst):
    lines = open(src, encoding="utf-8").read().replace("\r", "").split("\n")
    lines = [l for l in lines if not PROQUEST.match(l)]
    # body runs from the second "Introduction" heading (the first is in Contents) to "Appendix"
    starts = [i for i, l in enumerate(lines) if l.strip() == "Introduction"]
    start = starts[-1] if starts else 0
    end = next((i for i, l in enumerate(lines) if i > start and re.match(r"^Appendix(\s+\d+)?$", l.strip())), len(lines))
    body = lines[start:end]

    out, buf, glue = [], "", False
    def flush():
        nonlocal buf
        if buf.strip():
            out.append(re.sub(r"\s+", " ", buf).strip())
        buf = ""
    i = 0
    while i < len(body):
        l = body[i].rstrip()
        s = l.strip()
        i += 1
        if not s or re.fullmatch(r"\d{1,3}", s) or HEAD_LINE.match(s):
            continue
        if s in CH:                      # chapter title, preceded by its number line
            flush(); out.append(""); out.append(s.upper()); out.append(""); continue
        if re.match(r"^(Figure|Map) \d+\.", s):
            continue                     # captions
        m = HEAD_GLUED.search(l)
        if m and m.start() > 0 and l[m.start()-1].isalpha():
            l = l[:m.start()]; glue = True   # word split by a page break
        l = NOTE.sub(lambda mm: "", l)
        l = re.sub(r"([.,;:?!”’)])([A-Z“])", r"\1 \2", l)
        if glue and buf:
            buf = buf.rstrip() + l.strip() if buf.rstrip()[-1:].isalpha() and not l.startswith(" ") else buf + " " + l.strip()
            glue = False
        else:
            buf += " " + l.strip()
        # paragraph break: short line ending a sentence
        if len(s) < 60 and re.search(r"[.?!”]$", s):
            flush(); out.append("")
    flush()
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    open(dst, "w", encoding="utf-8").write(text.strip() + "\n")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
