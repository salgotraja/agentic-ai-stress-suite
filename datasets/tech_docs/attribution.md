# Technical Documentation Attribution

This directory contains curated technical documentation for RAG testing purposes.

## Dataset Composition

**Total**: ~200 documentation files (50 per framework)
**Purpose**: Comprehensive testing of RAG systems including multi-hop queries, entity relationships, and cross-framework comparisons
**Coverage**: Core concepts, advanced patterns, integration examples, best practices

## How this corpus was produced

This is not an untouched snapshot of the official documentation. A small set
of early files was adapted from the official docs listed below. Most files,
roughly 170 of 200, were written by an LLM with `scripts/generate_tech_docs.py`
from a per-framework topic list, in the style of that documentation. The
generated files were checked for length and format, not reviewed line by line
for technical accuracy. Treat the corpus as a retrieval test bed, not as a
reference for the frameworks it describes.

The questions and expected answers in `datasets/synthetic_queries/` were also
LLM-generated with `scripts/generate_queries.py`. See the `label_policy` field
in each query file for how source labels were assigned.

## Sources

### FastAPI (~50 files)
- **Source**: FastAPI official documentation (https://fastapi.tiangolo.com/)
- **License**: MIT License
- **Copyright**: © 2018-2024 Sebastián Ramírez
- **Files**: `fastapi/01-50_*.md`
- **Topics**: Routing, dependencies, async, testing, security, deployment, performance
- **Last Updated**: 2026-01-14

### Spring Framework (~50 files)
- **Source**: Spring Framework official documentation (https://spring.io/projects/spring-framework)
- **License**: Apache License 2.0
- **Copyright**: © 2002-2024 Pivotal Software, Inc.
- **Files**: `spring/01-50_*.md`
- **Topics**: IoC, Spring Boot, MVC, Data, Security, WebFlux, Cloud, Testing
- **Last Updated**: 2026-01-14

### React (~50 files)
- **Source**: React official documentation (https://react.dev/)
- **License**: MIT License
- **Copyright**: © 2013-2024 Meta Platforms, Inc.
- **Files**: `react/01-50_*.md`
- **Topics**: Components, Hooks, Router, State Management, Testing, Performance, Patterns
- **Last Updated**: 2026-01-14

### Pydantic (~50 files)
- **Source**: Pydantic official documentation (https://docs.pydantic.dev/)
- **License**: MIT License
- **Copyright**: © 2017-2024 Samuel Colvin and contributors
- **Files**: `pydantic/01-50_*.md`
- **Topics**: Models, Validation, Settings, JSON Schema, FastAPI Integration, Performance
- **Last Updated**: 2026-01-14

## License Summary

| Framework | License | Source |
|-----------|---------|--------|
| FastAPI | MIT | https://github.com/tiangolo/fastapi |
| Spring Framework | Apache 2.0 | https://github.com/spring-projects/spring-framework |
| React | MIT | https://github.com/facebook/react |
| Pydantic | MIT | https://github.com/pydantic/pydantic |

## Attribution Requirements

All documentation in this dataset is derived from open-source projects with permissive licenses. When using this dataset:

1. **FastAPI**: Copyright © 2018-2024 Sebastián Ramírez. Licensed under MIT License.
2. **Spring Framework**: Copyright © 2002-2024 Pivotal Software, Inc. Licensed under Apache License 2.0.
3. **React**: Copyright © 2013-2024 Meta Platforms, Inc. Licensed under MIT License.
4. **Pydantic**: Copyright © 2017-2024 Samuel Colvin. Licensed under MIT License.

## Usage

This dataset is intended for:
- RAG system testing and benchmarking
- Graph RAG multi-hop query evaluation
- Framework comparison and relationship discovery
- Educational purposes
- Research in information retrieval

## Cross-Framework Relationships

The documentation includes intentional cross-references to test multi-hop queries:
- **FastAPI ↔ Pydantic**: Data validation integration
- **Spring ↔ React**: Backend-frontend patterns
- **FastAPI ↔ Spring**: Web framework comparisons
- **React Hooks ↔ Spring Reactive**: Reactive programming patterns

## License Compliance

This project respects all upstream licenses. Content is used under the terms of each project's respective license. If you believe any content violates licensing terms, please open an issue immediately.

## Modifications

All documentation has been:
- Reformatted to markdown for consistent parsing
- Condensed and curated for RAG testing (800-1500 words per file)
- Organized by topic with clear file naming
- Enhanced with cross-references to other frameworks
- Optimized for entity extraction and relationship mapping

## Disclaimer

This dataset is for testing purposes only. Original documentation should always be consulted for:
- Production implementations
- Authoritative API references
- Latest feature updates
- Official best practices

## Contributing

To expand this dataset:
1. Ensure proper attribution
2. Verify license compatibility
3. Maintain consistent formatting
4. Add cross-references where relevant
5. Update this attribution file

## Acknowledgments

We thank the maintainers and contributors of FastAPI, Spring Framework, React, and Pydantic for creating excellent open-source software and documentation that makes this testing dataset possible.
