# kb/

Each agent profile reads from a knowledge base under this directory. The bundled `personal-agent` profile reads from `kb/` directly (resume, projects, codebases, meta). To add your own profile, point its `kb_root` at a subfolder here and drop in markdown/text files.

Real KB contents are gitignored — only this README and `kb/frampton/` (a public third-party Fextralife scrape) are tracked.
