# Roadmap v0.0.6 — Prototipo Funcional Completo

> **Estado:** Fases 1-4 completadas (skill tree DB, learner model lib, skill_planner subagent, onboarding trigger). Fases 5-14 pendientes.
>
> **Objetivo:** Un prototipo donde el usuario onboarda → el sistema construye su skill tree → el usuario entra a una sesión de aprendizaje guiada por un Maestro → un Evaluador mide su progreso → el Study Planner genera y adapta un plan de estudio → el usuario puede cambiar de meta y el sistema se adapta.

---

## 1. Filosofía del Proyecto

### 1.1 Cognits no es una guía, es un copiloto de proyecto

Cognits NO debe ser un sistema rígido que dice "haz A, luego B, luego C". Debe ser un **copiloto de proyecto** donde el usuario puede:

- Cambiar su visión a mitad del camino ("ya no quiero hacer top-down, quiero side-scroller").
- Tener nuevas ideas ("¿y si le añado audio procedural?").
- Descartar direcciones ("no me importa el narrative design").
- El sistema se adapta a esos cambios sin perder el progreso ya adquirido.

**El copilot metaphor es la diferencia clave frente a todo sistema comercial de adaptive learning.** Ningún plataforma (ALEKS, Khan Academy, Century Tech, Squirrel AI) maneja goal revision gracefully. Su currículo es fijo; el learner model se adapta pero la meta no. Cognits innova aquí.

### 1.2 Las IAs pueden equivocarse — guiar, no crear

Otro principio fundamental: los LLMs pueden alucinar. Cognits **no debe crear conocimiento de la nada**, sino guiar al usuario hasta el conocimiento ya establecido como documentación, papers, tutoriales oficiales.

Esto se materializa en:
- El **skill_planner** construye el árbol desde fuentes web verificadas (via `web_researcher`), no desde el conocimiento interno del LLM.
- El **Evaluador** prepara preguntas+rubrics grounded en RAG (los reports ya indexados) y solo va a la web si RAG está vacío. Cada expected answer **cita su fuente**.
- El **Maestro** deploya al **documentalista** para informarse antes de enseñar, en lugar de enseñar desde su memoria.
- Los reports persistidos y RAG-indexados acumulan conocimiento verificado sesión tras sesión.

### 1.3 Skill Tree ≠ Roadmap

Esta separación es arquitecturalmente crítica y SOTA la confirma (ITS 4-component model):

- **Skill Tree** (domain model): DAG estático de dependencias de prerequisitos. "Para aprender X necesitas Y primero." Sin timing, sin "fases", sin cronograma. Mutable cuando el usuario cambia de meta (añadir/podar ramas), no cuando el usuario progresa (eso actualiza el learner model).
- **Study Plan** (pedagogical model): Secuencia personalizada, time-bound, mutable, de sessions de aprendizaje. Se genera consumiendo (skill_tree, learner_model, prioridades del usuario). Se re-genera cuando cualquiera de los tres cambia.

### 1.4 Enseñar ≠ Evaluar — la metáfora del profesor de examen oficial

El Maestro enseña y acompaña, pero **no evalúa**. El Evaluador crea las preguntas y las corrige. Es como un profesor que prepara a un alumno para un examen oficial de acceso a la universidad: enseña, guía, acompañar — pero no escribe el examen ni lo corrige.

Esto evita el sesgo de "confirmation bias" (quien pregunta tiende a interpretar favorablemente las respuestas que recibe). El Evaluador es un agente separado con acceso a fuentes externas y rúbricas objetivas.

---

## 2. Hallazgos SOTA que informan el diseño

> Fuentes: briefing @SOTAbriefing 2026-06-30. Citas completas en el briefing original.

### 2.1 Skill tree construction
- **Auto-HKG** (PVLDB 2026): LLM pipeline para construir knowledge graphs. 324 conceptos para matemática de secundaria. 90% precisión en extracción de conceptos, 75% en categorías gruesas.
- **ESCO-PrereqSkill** (arXiv 2507.18479, 2025): Benchmark de 3.196 skills. DeepSeek-V3 logra F1 ≈ 0.82 en zero-shot prerequisite prediction. La calidad de LLM-generated prereq graphs es ~80-85%, no 90%+.
- **Ninguna plataforma comercial muta el skill tree mid-learning.** ALEKS y Math Academy actualizan el learner model, no el grafo. Cognits puede innovar aquí.

### 2.2 Learner model
- **IntelligenceCode** (EACL 2026): BKT ligero + FSRS + LLM. Cold-start con priors Beta(1,1), converge en 2-3 interacciones.
- **Khan Academy**: 5 niveles mastery (Not Started → Attempted → Familiar → Proficient → Mastered). Nosotros añadimos un 6º: Decaying.
- **FSRS-6** (Anki 24.11+): 21 parámetros, decay=0.1542. SOTA en spaced repetition, supera SM-2 al 99.5% de usuarios.

### 2.3 Study Planner / Path generation
- **Math Academy**: Task-selection algorithm maximiza learning/time usando mastery gating + layering + spaced repetition + interleaving. Computa la "knowledge frontier" — límite entre conocido y desconocido.
- **CG-RAG** (Auto-HKG paper): BKT → graph traversal → if weak, retrieve prereqs; if strong, retrieve successors.
- **Algoritmo base**: Topological sort over DAG → filter to knowledge frontier → rank by priority/time → produce session sequence. Suficiente para MVP.

### 2.4 Copilot philosophy
- **No existe en educational AI.** El copilot metaphor vive en coding assistants (Cursor, GitHub Copilot), no en tutoring systems.
- **PBL + AI** (Edutopia 2025): AI tools for project-based learning son teacher-facing, no student-facing copilots.
- **OECD Digital Education Outlook 2026**: "self-directed learning + AI agents" como emerging trend, no deployed.
- **Cognits tiene espacio real para innovar.** La filosofía copilot debería documentarse como principio de diseño explícito.

---

## 3. Arquitectura — ITS 4-Component Model

```
┌──────────────────────────────────────────────────────────┐
│ Project (first-class entity — futuro v0.1.X)              │
│  goal: "2D pixel art game in Godot"                       │
│  skill_tree_snapshot: tree@version N                      │
│  study_plan: [session_1, session_2, ...] (mutable)        │
│  learner_model: per-skill BKT/FSRS state                  │
│  changelog: [{diff, reason, timestamp}]                   │
├──────────────────────────────────────────────────────────┤
│ Domain Model          Pedagogical Model                   │
│  (Skill Tree)          (Study Planner)                    │
│  - DAG de prereqs      - consume (tree, learner_model,    │
│  - hard/soft edges        time_budget, priorities)        │
│  - mutable: add/prune  - genera study_plan persistente    │
│  - versioned            - se re-plana al cambiar goals     │
├──────────────────────────────────────────────────────────┤
│ Learner Model         Interface                          │
│  - BKT per skill       - "New free session" → chat libre  │
│  - FSRS review sched   - "New learning session" → chat    │
│  - status_enum           con Orchestrator en modo planning│
│    (not_seen →           - Sin vista visual del skill tree│
│     exploring →           (defer a v0.0.7+)              │
│     practicing →                                        │
│     proficient →                                        │
│     mastered →                                         │
│     decaying)                                           │
└──────────────────────────────────────────────────────────┘
```

### Edges typados en el skill tree
- `prereq` (hard): debes dominar el prereq antes de aprender este skill. Gate estricto.
- `soft_prereq` (nuevo en Fase 5): recomendado pero no obligatorio. El planner puede saltarlo si hay time constraints.
- `coreq`: se aprenden juntos.
- `related`: conexión débil, no bloquea.

---

## 4. Subagentes — Diseño Detallado

### 4.1 Evaluador (Fase 11)

**Identidad:** Un agente examinador independiente que crea preguntas objetivas grounded en fuentes verificadas, y las corrige contra rúbricas. No enseña. No acompaña. Solo examina y puntúa.

**Por qué es separado del Maestro:** evita el sesgo de confirmation bias (quien enseña tiende a interpretar favorablemente las respuestas). La separación enseñar/examinar es patrón estándar en exámenes oficiales.

**Flujo de 2 fases:**

#### Phase 1 — Crear preguntas + rubrics
```
Maestro deploya:
  deploy_subagent("evaluador", "Create assessment questions for skill X,
    user profile: {background, experience}. Generate N questions with
    expected answers, rubrics, and source citations.")

Evaluador Phase 1:
  1. rag_search("skill X") → leer reports indexados
  2. si RAG sparse → deploy_subagent("web_researcher", "skill X fundamentals")
  3. Genera N questions, cada una con:
     - question: el enunciado
     - expected_answer: respuesta esperada
     - rubric: criteria de correctness (qué hace una respuesta correcta/incorrecta)
     - source: URL o report_id que respalda el expected_answer
     - difficulty: 0.0-1.0
     - skill_id: el skill que esta pregunta evalúa
  4. Devuelve al Maestro: {questions: [...]}
```

#### Phase 2 — Graduar respuestas
```
Maestro deploya:
  deploy_subagent("evaluador", "Grade answers for skill X",
                  answers=[{question, user_answer, rubric, source, expected_answer}])

Evaluador Phase 2:
  1. Para cada respuesta: compara user_answer contra expected_answer + rubric
  2. Calcula correctness ∈ [0, 1] por pregunta
  3. Verifica contra fuente si hay ambigüedad
  4. Agrega: correctness promedio, distribución, misconceptions detectadas
  5. update_mastery(skill_id, correctness, rating, hints_used=0)
     → llama record_review() de learner/model.py
     → actualiza α/β/p_mastery/stability/reps/next_review/status_enum
     → persiste en learner_state via ReportStore.upsert_learner_state()
  6. Devuelve al Maestro: {
       summary: "3/5 correct, misconception on signals",
       p_mastery_before: 0.45,
       p_mastery_after: 0.72,
       status: "practicing",
       misconceptions: ["confused signals with events"],
       next_review: "2026-07-05T..."
     }
```

**Tools del Evaluador:**
- `rag_search(query)`: busca en knowledge base local.
- `deploy_subagent("web_researcher", query)`: investigación web si RAG es insuficiente.
- `update_mastery(skill_id, correctness, rating, hints_used)`: actualiza learner_state. Internamente llama `record_review()` de `learner/model.py`.

**Mitigación de alucinación:** si el Evaluador no encuentra fuente fiable para un expected_answer, marca la pregunta como `low_confidence: true`. El Maestro usa esa pregunta para discusión, no para scoring.

### 4.2 Maestro (Fase 12)

**Identidad:** Un tutor Socrático que enseña un skill concreto del skill tree. Acompaña al estudiante durante la evaluación sin evaluarle. Comunica los resultados del Evaluador al usuario.

**Por qué Socrático y no expositivo:** la filosofía del proyecto es que el usuario descubra respuestas por sí mismo. El Maestro guía con preguntas, no da soluciones hasta que el usuario ha razonado.

**Flujo de una sesión de aprendizaje:**
```
Maestro recibe: {skill_id, skill_name, skill_description, prerequisites: [...],
                 learner_state: {p_mastery, status, reps}, user_profile: {...}}

1. Informarse:
   deploy_subagent("documentalista", "skill X fundamentals, documentation,
     examples, common misconceptions")
   → documentalista RAG-searches (+ web_researcher si necesario) → report

2. Enseñar (Socrático):
   - Explica conceptos progresivamente
   - Usa ejemplos del report del documentalista
   - Pregunta al usuario para verificar comprensión
   - Si el usuario demina misconception grave → re-enseña antes de continuar

3. Evaluar:
   deploy_subagent("evaluador", Phase 1: "Create assessment questions for skill X,
     profile P")
   → recibe {questions + rubrics + sources}

4. Acompañar evaluación:
   - Pregunta una a una al usuario
   - NO dice si las respuestas son correctas o incorrectas
   - Si el usuario se atasca, puede dar hints (registrar hints_used)
   - NO evalúa — solo acompaña

5. Graduar:
   deploy_subagent("evaluador", Phase 2: "Grade answers", answers=[...])
   → recibe {summary, p_mastery_before, p_mastery_after, status, misconceptions}

6. Comunicar:
   - Resume al usuario: "Your mastery of X is now 78% (practicing).
     You had a misconception on signals vs events — let's review that."
   - Si mastery < threshold → recomienda repaso
   - Si mastery ≥ threshold → Recommends next skill

7. Persistir:
   - El Evaluador ya actualizó learner_state via update_mastery
   - El Maestro registra la session como completada (para el study plan)
```

**Tools del Maestro:**
- `deploy_subagent("documentalista", query)`: obtiene fuentes autorizadas antes de enseñar.
- `deploy_subagent("evaluador", query)`: crea preguntas (Phase 1) y las gradúa (Phase 2).
- `get_learner_state(skill_id)`: lee el estado actual del usuario en el skill.
- `get_skill(skill_id)`: lee metadatos del skill (name, description, prereqs, bloom_level).

**El Maestro NO tiene acceso a `update_mastery`.** Solo el Evaluador actualiza el learner model. Esto es un invariant arquitectural: enseñar y evaluar son responsabilidades separadas.

### 4.3 Study Planner / Arquitecto (Fase 8)

**Identidad:** Un planificador que consume el skill tree + el learner model + las prioridades del usuario para generar un plan de estudio persistente y mutable.

**Algoritmo base (SOTA):**
```
1. Topological sort sobre el DAG de skills (prereqs first)
2. Filter to "knowledge frontier":
   - skills whose hard prereqs are all mastered (p_mastery ≥ 0.80)
   - skills not yet mastered (p_mastery < 0.95)
3. Rank by:
   - user_priority (skills que el user quiere aprender explícitamente)
   - mastery_gap (skills cercanos al threshold de mastery)
   - path_to_goal (skills en el camino más corto al objetivo del usuario)
4. Soft prereqs: no bloquean pero bajan el score
5. Emit study_plan: secuencia de items, cada uno con:
   - skill_id
   - mode: "socratic" | "exercise" | "project"
   - estimated_duration: horas (opcional, el user ajusta)
   - priority: high | medium | low
```

**Mutabilidad del plan:**
- Si el user necesita más sesiones de repaso → insertar items de repaso (FSRS schedule).
- Si el user cambia de meta → re-generar plan sobre el nuevo subgrafo activo.
- Si el user descarta una rama → marcar items como `goal_removed` (no borrar).
- El plan almacena `tree_version` para detectar staleness.

**Tools del Study Planner:**
- `get_skill_tree()`: lee el árbol completo (nodes + edges).
- `get_learner_state(skill_id)`: lee el mastery del user en un skill.
- `save_study_plan(plan)`: persiste el plan en `study_plans` + `study_plan_items`.

### 4.4 Orchestrator modo planning (Fase 9)

El Orchestrator tiene dos modos:
- **Modo libre** (actual): chat Socrático sin plan. El user pregunta lo que quiere.
- **Modo planning** (nuevo): se activa al clicar "Nueva sesión de aprendizaje".

**Modo planning — flujo:**
```
1. Orchestrator recibe contexto: skill_tree + learner_state de todos los skills
2. Computa "knowledge frontier":
   - skills disponibles para aprender ahora (prereqs dominados, skill no dominado)
3. Presenta al user:
   "Tienes estas skills disponibles para aprender:
    - GDScript Syntax (prereqs: Programming Fundamentals ✓)
    - Nodes and Scene System (prereqs: OOP ✓)
    ¿Cuál te interesa? También puedo recommendarte una."
4. Conversa Socráticamente:
   - Si el user quiere saltar a algo con prereqs no dominados:
     "Para aprender FSMs necesitas Signals y Nodes primero.
      ¿Los dominas? [consulta learner_state]"
   - Si el user pide un plan completo:
     deploy_subagent("study_planner", "Generate study plan for goal X,
       skills: [...], learner_states: [...], priorities: [...]")
5. Cuando el user elige un skill:
   - Crea una "learning session" (session con agent_id="maestro", skill_id=X)
   - El Maestro toma el relevo en esa session
```

**Socratic planning** — el patrón novedoso: el Orchestrator no solo enseña Socráticamente, también planea Socráticamente. Guía al usuario a descubrir qué necesita aprender, no le impone un orden.

---

## 5. Esquema de Base de Datos — Tablas Pendientes

### 5.1 Modificaciones a tablas existentes (Fase 5)

```sql
-- skill_prerequisites: añadir soft_prereq al CHECK de edge_type
ALTER TABLE skill_prerequisites
  DROP CONSTRAINT IF EXISTS check_edge_type;
-- (En práctica: como v0.0.X es fresh, se edita el DDL directamente)
-- edge_type CHECK IN ('prereq','coreq','related','soft_prereq')

-- skills: añadir tree_version
-- (columna entera, incrementa cuando el árbol se muta estructuralmente)
```

Como v0.0.X es fresh (sin migración), se editan los DDLs en `BASE_SCHEMA` directamente.

### 5.2 Nuevas tablas (Fase 7)

```sql
-- Un plan de estudio por usuario (uno activo a la vez en v0.0.6)
CREATE TABLE IF NOT EXISTS study_plans (
    id TEXT PRIMARY KEY,
    session_id TEXT,                  -- session donde se generó
    tree_version INTEGER NOT NULL,    -- snapshot del árbol al generar
    goal TEXT NOT NULL DEFAULT '',    -- meta del usuario al generar
    status TEXT NOT NULL DEFAULT 'active',  -- active | superseded
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Items del plan (cada uno = una session de aprendizaje pendiente)
CREATE TABLE IF NOT EXISTS study_plan_items (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'socratic',  -- socratic | exercise | project
    status TEXT NOT NULL DEFAULT 'pending', -- pending | in_progress | done | skipped | goal_removed
    order_index INTEGER NOT NULL DEFAULT 0,
    estimated_duration_min INTEGER,  -- opcional
    actual_duration_min INTEGER,     -- заполняется al completar
    learning_session_id TEXT,        -- session donde se impartió (si done)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (plan_id) REFERENCES study_plans(id),
    FOREIGN KEY (skill_id) REFERENCES skills(id)
);
CREATE INDEX IF NOT EXISTS idx_plan_items_plan ON study_plan_items(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_items_status ON study_plan_items(status);
```

### 5.3 Skills: añadir tree_version (Fase 5)

Columna `tree_version INTEGER NOT NULL DEFAULT 1` en la tabla `skills`. Incrementa cuando se muta el árbol (add_branch, prune_branch, re_eval_prereqs). El study_plan referencia este version para detectar staleness.

---

## 6. API REST — Endpoints Pendientes (Fase 6)

```python
# GET /api/skills
# Devuelve lista de skills con su learner_state embebido
# Response: {skills: [{id, domain, name, status, p_mastery, status_enum, ...}]}

# GET /api/skills/tree
# Devuelve el árbol completo (nodes + edges) para visualización
# Response: {skills: [...], edges: [...], tree_version: N}

# GET /api/skills/{skill_id}/state
# Devuelve el learner_state de un skill concreto
# Response: {skill_id, alpha, beta, p_mastery, status_enum, reps, ...}

# GET /api/study-plan
# Devuelve el plan activo
# Response: {id, tree_version, goal, items: [{skill_id, mode, status, ...}]}

# POST /api/study-plan
# Crea/genera un nuevo plan (triggers study_planner subagent)
# Body: {goal: "...", priorities: ["skill_id_1", ...]}
# Response: {plan_id, items: [...]}
```

---

## 7. Frontend — Dos Botones de Sesión (Fase 10)

### Cambios en la UI:
1. El botón "New Session" actual se renombra a "New Free Session".
2. Se añade un segundo botón: "New Learning Session".
3. Al clicar "New Learning Session":
   - Se crea una session con `agent_id="orchestrator"` y un flag `mode="planning"`.
   - Se envía un hidden message: `"Start planning mode. Present the user's
     knowledge frontier and recommend the next skill to learn."`
   - El Orchestrator entra en modo planning (sección del prompt activada).
4. No hay vista visual del skill tree en v0.0.6 (defer a v0.0.7). El user interactúa solo via chat.

### Frontend files a tocar:
- `frontend/src/components/Sidebar.tsx` (o donde esté el "New Session" button): añadir segundo botón.
- `frontend/src/stores/session-store.ts`: `createNewSession(mode?)` — acepta un modo opcional.
- `frontend/src/stores/chat-store.ts`: si la session tiene `mode="planning"`, enviar el hidden message de planning.

---

## 8. Fases de Implementación — Detalle

### Fase 5 — Cimientos (1 commit)

**Archivo:** `src/cognits/storage/db.py`
- `skill_prerequisites` edge_type CHECK: añadir `'soft_prereq'`.
- `skills`: añadir columna `tree_version INTEGER NOT NULL DEFAULT 1`.
- `SKILL_PLANNER_SYSTEM_PROMPT` en `subagents.py`: editar la sección "Final Markdown report" para **prohibir timing** ("fases", "semanas", "cronograma"). El output debe ser SOLO el DAG + raíces + notes. El timing lo hace el Study Planner.

**Commit:** `feat(skill-tree): soft_prereq edges + tree_version + remove timing from skill_planner output`

### Fase 6 — API de Skills (1 commit)

**Archivos:** `src/cognits/server/routes_misc.py` (o nuevo `routes_skills.py`)
- `GET /api/skills`: lista de skills con learner_state embebido.
- `GET /api/skills/tree`: árbol completo (nodes + edges + tree_version).
- `GET /api/skills/{skill_id}/state`: learner_state de un skill.

**Tests:** `tests/test_skills_api.py` — round-trip con ReportStore real.

**Commit:** `feat(api): skill tree + learner state read endpoints`

### Fase 7 — DB: Study Plans (1 commit)

**Archivo:** `src/cognits/storage/db.py`
- DDL de `study_plans` + `study_plan_items` en `BASE_SCHEMA`.
- Dataclasses `StudyPlan`, `StudyPlanItem`.
- Métodos en `ReportStore`: `create_plan`, `add_plan_item`, `update_plan_item`, `get_active_plan`, `get_plan_items`, `supersede_plan`.

**Tests:** `tests/test_db.py` — round-trip plan + items.

**Commit:** `feat(db): study_plans + study_plan_items tables + store methods`

### Fase 8 — Study Planner subagente (2-3 commits)

**Archivo nuevo:** `src/cognits/agent/tool_study_plan.py`
- Tool `save_study_plan`: persiste plan + items en `study_plans`/`study_plan_items`.

**Archivo:** `src/cognits/agent/subagents.py`
- Const `STUDY_PLANNER_SYSTEM_PROMPT` en inglés: persona del arquitecto. Recibe (skill_tree, learner_states, user_priorities, time_budget). Algoritmo: topological sort → filter frontier → rank → emit plan. Sin timing detallado en v0.0.6 (solo orden + mode + skill_id).
- Factory `study_planner_config(...)`.

**Archivo:** `src/cognits/agent/tool_deploy.py`
- Enum añade `"study_planner"`.

**Archivo:** `src/cognits/server/routes_chat.py`
- Inyectar study_planner en subagent_map.

**Tests:** `tests/test_study_planner.py` — config, tool round-trip, end-to-end con ScriptedLLM.

**Commits:**
1. `feat(study_planner): subagente + save_study_plan tool`
2. `feat(study_planner): wiring + tests`

### Fase 9 — Orchestrator modo planning (1-2 commits)

**Archivo:** `src/cognits/agent/prompts.py`
- `ORCHESTRATOR_SYSTEM_PROMPT`: añadir sección "Planning Mode" que describe:
  - Cuando se activa (hidden message "Start planning mode...")
  - Cómo computar knowledge frontier
  - Cómo presentar y recomendar
  - Cómo crear una learning session (vinculada a skill_id)
  - deploy_subagent("study_planner") si el user pide un plan completo

**Archivo:** `src/cognits/server/routes_chat.py`
- Si la session tiene `mode="planning"`, añadir el skill_tree + learner_states al system prompt.
- Puede requerir un campo `mode` en SessionConfigRow.

**Tests:** `tests/test_planning_mode.py` — ScriptedLLM, verificar que el orchestrator presenta frontier y crea learning session.

**Commit:** `feat(orchestrator): planning mode — knowledge frontier + session creation`

### Fase 10 — Frontend: dos botones (2 commits)

**Files:**
- `frontend/src/stores/session-store.ts`: `createNewSession(mode?)`.
- Component del sidebar: segundo botón.
- `frontend/src/stores/chat-store.ts`: planning hidden message.
- `frontend/src/App.tsx`: routing por mode.

**Commits:**
1. `feat(frontend): two session buttons — free vs learning`
2. `feat(frontend): planning mode hidden message trigger`

### Fase 11 — Evaluador subagente (2-3 commits)

**Archivo nuevo:** `src/cognits/agent/tool_mastery.py`
- Tool `update_mastery(skill_id, correctness, rating, hints_used=0)`:
 - Lee `learner_state` de `ReportStore`.
  - Llama `record_review()` de `learner/model.py`.
  - Persiste con `upsert_learner_state()`.
  - Devuelve `{p_mastery_before, p_mastery_after, status, next_review}`.

**Archivo:** `src/cognits/agent/subagents.py`
- Const `EVALUATOR_SYSTEM_PROMPT` en inglés: persona del examinador. Crea preguntas grounded. Gradua contra rubrics. Cita fuentes. Si no hay fuente fiable → `low_confidence`.
- Factory `evaluator_config(...)`.

**Archivo:** `src/cognits/agent/tool_deploy.py`
- Enum añade `"evaluator"`.

**Archivo:** `src/cognits/server/routes_chat.py`
- Inyectar evaluator en subagent_map (siempre disponible, no requiere TinyFish).

**Tests:** `tests/test_evaluator.py` — config, update_mastery tool round-trip, Phase 1 + Phase 2 con ScriptedLLM.

**Commits:**
1. `feat(evaluator): update_mastery tool + subagente config`
2. `feat(evaluator): wiring + Phase 1/Phase 2 tests`

### Fase 12 — Maestro subagente (2-3 commits)

**Archivo:** `src/cognits/agent/subagents.py`
- Const `TEACHER_SYSTEM_PROMPT` en inglés: persona Socrática. Enseña un skill concreto. Deploya documentalista para informarse. Deploya evaluador (Phase 1: crear preguntas, Phase 2: graduar). Acompaña sin evaluar. Comunica score al final.
- Factory `teacher_config(...)`.

**Archivo:** `src/cognits/agent/tool_deploy.py`
- Enum añade `"teacher"` (aunque el Maestro se asigna como agent_id de la session, no como tool deploy).

**Archivo:** `src/cognits/server/routes_chat.py`
- Si `agent_id == "teacher"`: construir config del Maestro con tools (documentalista + evaluador + get_skill + get_learner_state).
- Inyectar en subagent_map.

**Tests:** `tests/test_teacher.py` — ScriptedLLM full flow: enseñar → evaluar Phase 1 → acompañar → evaluar Phase 2 → comunicar score.

**Commits:**
1. `feat(teacher): Socratic subagente — teach + delegate evaluation`
2. `feat(teacher): wiring + full flow tests`

### Fase 13 — Wiring final (1 commit)

- Orchestrator en modo planning puede crear sessions con `agent_id="teacher"`.
- Learning sessions activan el Maestro automáticamente.
- Smoke test end-to-end.

**Commit:** `feat(wiring): learning sessions activate teacher, planning creates them`

### Fase 14 — Smoke test + publish (1 commit)

- `pyproject.toml`: versión sigue `0.0.6`.
- `scripts/build.sh` + `scripts/test_install.sh` + `cognits --version`.
- Prueba manual end-to-end completa.

**Commit:** `chore(release): v0.0.6 smoke test + reinstall`

---

## 9. Flujo Completo del Usuario (al terminar v0.0.6)

```
1. Usuario arranca Cognits (fresh, sin .cognits/)
   → Onboarding: system_support entrevista (5-10 preguntas)
   → finish_setup → skill_planner construye árbol (visible en Reports)
   → setup_complete → UI principal

2. Usuario clica "Nueva sesión libre"
   → Chat con Orchestrator (Socratic tutoring libre, sin plan)
   → Como hoy: pregunta lo que quiera

3. Usuario clica "Nueva sesión de aprendizaje"
   → Chat con Orchestrator en modo planning
   → Orchestrator presenta knowledge frontier:
     "Tienes estas skills disponibles:
      - GDScript Syntax (prereqs dominados ✓)
      - Nodes and Scene System (prereqs dominados ✓)
      - Sprite Animation (prereqs: Nodes pending)
      ¿Cuál te interesa?"
   → Conversa Socráticamente sobre qué aprender
   → Si el user pide un plan → deploy_subagent("study_planner")
     → Study Planner genera plan persistente
   → User elige un skill
   → Se crea una learning session (agent_id="maestro", skill_id=X)

4. Learning session con el Maestro:
   → Maestro deploya documentalista para sources
   → Enseña Socráticamente el skill X
   → Deploya evaluador Phase 1: crea preguntas + rubrics
   → Pregunta al usuario (acompaña sin evaluar)
   → Deploya evaluador Phase 2: gradúa + update_mastery
   → Maestro comunica: "Tu mastery de X es ahora 78% (practicing).
     Tuvo un misconception on signals — repasemos?"
   → Si mastery OK → recomienda siguiente skill del plan

5. Usuario vuelve a planning → siguiente skill → repite ciclo

6. Usuario cambia de meta ("ya no quiero narrative design, quiero multiplayer"):
   → Lo comenta en planning chat
   → Orchestrator deploya skill_planner para añadir rama "multiplayer"
   → Study Planner re-genera plan
   → learner_state de skills ya practicas se preserva
```

---

## 10. Invariants Arquitecturales

1. **Enseñar ≠ Evaluar.** El Maestro nunca actualiza `learner_state`. Solo el Evaluador puede llamar `update_mastery`.
2. **Skill tree ≠ Roadmap.** El skill_planner no genera timing. El Study Planner no modifica el árbol.
3. **Grounding obligatorio.** Toda enseñanza/evaluación se basa en sources (RAG primero, web segundo). Expected answers citan su fuente.
4. **Persistencia atomica.** Toda mutación del skill tree o del study plan se persiste átomo a átomo (robusto ante cancelación).
5. **Prefix cache.** Tool definitions sorted by name. El prompt del Maestro no cambia entre sessions del mismo skill (construir system prompt una vez, cachearlo).
6. **El skill tree NO se muta cuando el usuario progresa.** Solo se muta cuando el usuario cambia de meta. El progreso se registra en `learner_state`.
7. **Soft prereqs no bloquean.** Solo `prereq` (hard) es gate estricto en el planner.
8. **Idioma: prompts en inglés, agente se adapta.** Todos los system prompts están en inglés. El agente responde en el idioma del usuario.

---

## 11. Para Versiones Futuras (v0.0.7+)

- **Vista visual del skill tree** (DAG render, lista colapsable, o tree jerárquico).
- **Mutación del árbol como first-class** (add_branch, prune_branch, re_eval_prereqs como workflows de subagente con plan diffing).
- **Formulador de ejercicios** subagente (genera práctica adaptativa para un skill, dependiente del Evaluador y del Maestro).
- **Multi-project entity** (generalizar StudentProfile a lista de Projects con snapshots).
- **DAG rendering interactivo** (d3/vis-network, zoom/pan, click para ver detalle).
- **Plan diffing visual** (mostrar qué cambió al mutar goals).
- **Schema version 2** con migración (v0.1.X — cuando empecemos a preservar datos entre versiones).
- **Tree versioning completo** (changelog de mutaciones, rollback).
- **Audio** y otros dominios diferidos que el skill_planner marqué como "future branches".

---

## 12. Estado Actual (Fases 1-4 completadas)

| Fase | Commit | Qué se hizo |
|---|---|---|
| 1 | `6665777` | DB: skills, skills_fts, skill_prerequisites, skill_builds, learner_state + SkillTreeStore |
| 2 | `fa4c7da` | Lib learner: FSRS-6 + BKT soft-evidence + 6 mastery levels + record_review |
| 3 | `f3c52b7` | Subagente skill_planner + tool skill_tree_save + wiring routes_chat |
| 4 | `622a844` | Trigger: finish_setup invoca skill_planner + SYSTEM_SUPPORT_PROMPT actualizado |
| fix | `f4ff00a` | Prompts en inglés (anti-regresión) |
| fix | `1e799bc` | Onboarding default English greeting |
| fix | `fa630c3` | Labels Skill Planner / Web Researcher en banner |

**Suite: 92/92 verde.** `cognits 0.0.6` instalado y funcional (onboarding → skill tree construction → chat libre).

---

*Documento generado el 2026-06-30. Actualizar conforme se implementen las fases pendientes.*