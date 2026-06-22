from pathlib import Path
out_dir = Path("course_output")
notes_files = sorted(out_dir.glob("*/notes.md"))
master = out_dir / "MASTER_NOTES.md"
with master.open("w", encoding="utf-8") as f:
    f.write(f"# AI Creator Course -- Complete Notes\n\n*{len(notes_files)} lessons*\n\n---\n\n")
    for nf in notes_files:
        f.write(f"\n\n{nf.read_text(encoding='utf-8')}\n\n---\n")
print(f"MASTER_NOTES.md: {len(notes_files)} lessons, {master.stat().st_size // 1024} KB")
