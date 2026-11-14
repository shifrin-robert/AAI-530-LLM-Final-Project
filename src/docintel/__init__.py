"""DocIntel AI: grounded document intelligence over uploaded PDFs.

The package is organised as a straightforward pipeline:

    pdf_processing -> chunking -> retrieval -> prompting -> llm_client -> grounding

with task workflows (``qa``, ``summarization``, ``extraction``, ``comparison``) composing
those stages, and ``session.DocumentWorkspace`` holding one user's documents in memory.
"""

__version__ = "1.0.0"
PRODUCT_NAME = "DocIntel AI"
