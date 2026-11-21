# System design templates

## Architecture report (McGonagall)
- Requirements and constraints
- Proposed architecture
- Component responsibilities
- Data flow
- API and interface boundaries
- Database selection and justification
- Security considerations
- Failure handling
- Scaling strategy
- Deployment considerations
- Observability
- Alternatives and trade-offs (table: option | pros | cons | why not)
- Risks
- Open decisions (need user approval)
- Expected implementation scope (files/components, Existing vs Proposed)

## HLD (Ron)
- Problem and scope
- Requirements (FR/NFR IDs)
- System architecture (Mermaid flowchart)
- Components
- Interfaces
- Data flow (Mermaid sequenceDiagram if useful)
- Database choices
- Integrations
- Security
- Reliability
- Scaling
- Deployment
- Observability
- Architectural trade-offs

## LLD (Ron)
- Modules and classes
- Functions and interfaces (signatures)
- Data structures
- Schemas (Mermaid erDiagram / DDL)
- API contracts (method, path, request, response, errors)
- Algorithms
- Validation
- Error handling
- Dependencies
- Unit tests
- Integration tests

Label each element **Existing (path:line)** or **Proposed**.
