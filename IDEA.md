# LearnIt: Documento de Arquitectura y Visión

## Sistema de tutoría inteligente personal multi-agente

**Versión de la idea 2.0 — 11 de junio de 2026**

---

## Índice

1. [Visión general](#1-visión-general)
2. [El estado del arte y las doce brechas que LearnIt cierra](#2-el-estado-del-arte-y-las-doce-brechas-que-learnit-cierra)
3. [Principios fundacionales](#3-principios-fundacionales)
4. [Arquitectura del sistema](#4-arquitectura-del-sistema)
5. [Modelo de dominio: Skill Trees auto-generados](#5-modelo-de-dominio-skill-trees-auto-generados)
6. [Modelo del estudiante](#6-modelo-del-estudiante)
7. [Modelo pedagógico](#7-modelo-pedagógico)
8. [Modelo de sesión: estructura, ritmo y adaptabilidad](#8-modelo-de-sesión-estructura-ritmo-y-adaptabilidad)
9. [Negociación de horario y gestión de asistencia](#9-negociación-de-horario-y-gestión-de-asistencia)
10. [Arquitectura multi-agente con verificación cruzada](#10-arquitectura-multi-agente-con-verificación-cruzada)
11. [Interfaz: CLI launcher + web local](#11-interfaz-cli-launcher--web-local)
12. [Stack técnico](#12-stack-técnico)
13. [Estructura de `.learnit/`](#13-estructura-de-learnit)
14. [Qué hace a LearnIt mejor que el SOTA actual](#14-qué-hace-a-learnit-mejor-que-el-sota-actual)
15. [Hoja de ruta](#15-hoja-de-ruta)
16. [Métricas de éxito](#16-métricas-de-éxito)
17. [Referencias](#17-referencias)

---

## 1. Visión general

LearnIt es un sistema de tutoría inteligente personal que opera desde el terminal del usuario como punto de entrada, con una interfaz web local para la interacción. Está anclado a la carpeta de un proyecto real del usuario (por ejemplo, aprender Godot para hacer un videojuego). A diferencia de los chatbots educativos genéricos, LearnIt mantiene un modelo de dominio estructurado, un modelo probabilístico del estudiante, y una arquitectura multi-agente con verificación cruzada que orquesta agentes especializados.

**Tesis central**: el SOTA actual en sistemas de tutoría inteligente adolece de fragmentación. Los sistemas o bien son potentes en knowledge tracing pero carecen de interfaz conversacional natural, o bien son LLMs conversacionales pero carecen de modelo de estudiante riguroso, verificación factual y grounding curricular. LearnIt integra ambas tradiciones —los modelos formales de los ITS clásicos y la flexibilidad conversacional de los LLMs— en una arquitectura unificada, portable, y centrada en el proyecto personal del usuario.

**Caso de uso paradigmático**: un astrofísico con programación avanzada en Python quiere aprender Godot para crear un juego de plataformas 2D. Sabe programar, pero desconoce el ecosistema Godot, GDScript, y los patrones de desarrollo de videojuegos. LearnIt diagnostica esta asimetría, genera automáticamente un Skill Tree desde la documentación de Godot, poda los conceptos que el usuario ya domina, y traza una ruta de aprendizaje personalizada. Durante las sesiones, el sistema enseña, propone ejercicios calibrados a su zona de flujo, ejecuta el código en Godot headless, detecta concepciones erróneas, y ajusta continuamente su estrategia pedagógica.

---

## 2. El estado del arte y las doce brechas que LearnIt cierra

La investigación realizada durante junio de 2026 —cubriendo revisiones sistemáticas en *Nature Scientific Reports*, *Frontiers in Computer Science*, *Artificial Intelligence Review*, NeurIPS 2025, NAACL 2025, LAK 2025, y el informe Stanford SCALE 2026— revela doce brechas en los sistemas de tutoría inteligente actuales.

| # | Brecha | Evidencia | Cómo la cierra LearnIt |
|---|--------|-----------|------------------------|
| 1 | **Sin benchmarks estandarizados de eficacia pedagógica** | Zerkouk et al. (2025): 127 artículos, métricas inconsistentes | Métricas cuantitativas integradas: Δ BKT, retención FSRS, zona de flujo, transferencia sin asistencia |
| 2 | **Sistemas multi-agente fallan 41-86.7%** | Cemri et al., NeurIPS 2025: 14 modos de fallo, ambigüedad de especificación | Contratos explícitos por agente, handoff único vía Orquestador, verificación cruzada obligatoria (CCVP) |
| 3 | **Alucinaciones como riesgo pedagógico grave** | EDM 2025: feedback erróneo en tutoría de matemáticas | Grounding obligatorio contra documentación indexada en vector store; CCVP en cada output |
| 4 | **Dimensión socioemocional ausente** | Fleig, UCSD 2025; Márquez-Carpintero et al., 2026 | Detección de fatiga y frustración vía señales textuales y patrones de interacción; adaptación de estrategia |
| 5 | **Cognitive offloading documentado** | Kosmyna et al., 2025; Gerlich, 2025; Stanford SCALE 2026 | Modo socrático por defecto; pausas metacognitivas forzadas; nunca solución sin razonamiento previo |
| 6 | **Sesgo en contenido y modelado** | Weissburg et al., 2024: LLMs asignan contenido por raza/género/ingresos | Perfilado transparente y auditable; BKT sin features demográficos; `.learnit/` editable por el usuario |
| 7 | **Estrechez de dominio: solo STEM** | Zerkouk et al., 2025: "abrumadoramente sesgado hacia STEM" | Arquitectura agnóstica al dominio; Skill Tree auto-generado desde cualquier documentación |
| 8 | **Sin estudios longitudinales** | Zerkouk et al., 2025: mayoría <6 semanas, <100 participantes | Persistencia completa en `.learnit/`; diseñado para meses de uso continuo; analíticas acumulativas |
| 9 | **Profesores excluidos del diseño** | Márquez-Carpintero et al., 2026 | Para uso personal no aplica; para uso compartido, `.learnit/` y `AGENTS.md` son auditables y versionables |
| 10 | **Modelado de estudiante superficial** | Zerkouk et al., 2025: overlay binario o basado en prompts | BKT con 4 parámetros por skill; FSRS con 17 parámetros personales; historial de concepciones erróneas; modelo afectivo |
| 11 | **Dependencia frágil de prompts** | Márquez-Carpintero et al., 2026: "altamente sensible a formulación" | Estrategia pedagógica gobernada por Q-table, no por prompts; prompts como parámetros versionados |
| 12 | **Fragmentación: tareas aisladas vs práctica holística** | Márquez-Carpintero et al., 2026 | Orquestador único que integra diagnóstico, enseñanza, práctica y reflexión en sesión coherente |

### Lo que SÍ funciona y LearnIt adopta

| Componente | Sistema de referencia | Resultado | Implementación en LearnIt |
|------------|----------------------|-----------|--------------------------|
| Knowledge tracing | MSKT (Nature 2025) | 91-95% AUC | BKT con 4 parámetros por skill, reestimación continua |
| Skill Trees | SkillTree IES (2025-26) + G4L EKSG | +24% ganancia de aprendizaje | `.learnit/domain/knowledge_graph.json` auto-generado |
| Dominio auto-generado | MMKG-RAG (Frontiers 2026) | F1 > 0.83, 100% automatizado | Pipeline doc → grafo con validación de baja ambigüedad |
| Repetición espaciada | FSRS v6 | 20-30% menos revisiones | `.learnit/student/fsrs_params.json` por usuario |
| Zona de flujo | ELA Tutor (Q-learning) | Engagement sostenido | Planificador calibra ejercicios a P(correct) ∈ [0.40, 0.70] |
| RAG parent-child | ParentDocumentRetriever | +10-15% accuracy | ChromaDB con splitting recursivo 400/1000 tokens |
| Chunking por AST | tree-sitter | +4.3 puntos Recall@5 | tree-sitter-gdscript para código del usuario |
| Rachas | Aulagnon et al. RCT (60K estudiantes) | +0.13 a +0.17 SD en rendimiento | Sistema de rachas con freezes integrado en la UI |

---

## 3. Principios fundacionales

1. **El proyecto del usuario es el currículum.** No hay un temario predefinido. El modelo de dominio se genera automáticamente a partir de la documentación del ecosistema que el usuario quiere aprender, podado por lo que ya sabe y enfocado en lo que necesita para su proyecto concreto.

2. **El usuario no es un estudiante pasivo.** Es un profesional que trae conocimiento asimétrico. El sistema diagnostica, no asume. Salta lo conocido, profundiza en lo nuevo.

3. **La terminal como punto de entrada, la web como espacio de aprendizaje.** El CLI lanza, actualiza y gestiona el ciclo de vida del programa. Toda la interacción ocurre en una interfaz web local limpia y enfocada.

4. **Persistencia total y portable.** Todo el estado del aprendizaje vive en `.learnit/`. Se versiona con git. Se comparte. Es auditable y editable por el usuario.

5. **La IA no da respuestas, guía el descubrimiento.** Modo socrático por defecto. La solución final solo se ofrece después de que el usuario ha razonado. Las pausas metacognitivas son forzadas, no opcionales.

6. **Verificación cruzada obligatoria.** Ningún subagente emite contenido pedagógico sin que otro subagente —o el Orquestador— verifique contra la base de conocimiento grounded.

7. **El sistema aprende a enseñarte.** La política pedagógica se optimiza continuamente según los resultados del usuario, no según un estándar externo.

8. **El tutor educa sobre cómo aprender, no solo sobre la materia.** La gestión de sesiones, pausas, fatiga y hábitos es parte de la enseñanza. El sistema guía activamente hacia las prácticas de aprendizaje óptimas, no obedece ciegamente cualquier demanda del usuario.

---

## 4. Arquitectura del sistema

```
                           ┌─────────────────┐
                           │   Usuario (CLI)  │
                           └────────┬────────┘
                                    │ learnit | learnit --update | learnit stop
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        ORQUESTADOR (DeepSeek V4 Pro Max)              │
│                                                                      │
│  - Carga perfil y estado de .learnit/ al iniciar sesión              │
│  - Decide qué subagente invocar en cada interacción                  │
│  - Aplica política pedagógica (Q-table)                              │
│  - Verifica outputs de subagentes (CCVP)                             │
│  - Sintetiza respuesta final para el usuario                         │
│  - Actualiza estado al finalizar interacción                         │
│  - Gestiona el ciclo de sesión: inicio, pausas, cierre               │
└───────┬──────┬──────┬──────┬──────┬──────┬──────┬────────────────────┘
        │      │      │      │      │      │      │
   ┌────▼──┐┌──▼───┐┌──▼───┐┌──▼───┐┌──▼───┐┌──▼───┐┌──▼──────────┐
   │DIAG-  ││PLANI-││DOCU-  ││BUSCA- ││ANALI- ││GENERA-││EJECUTOR    │
   │NOSTI- ││FICA- ││MENTA- ││DOR    ││ZADOR  ││DOR    ││(Godot      │
   │CADOR  ││DOR   ││LISTA  ││WEB    ││CÓDIGO ││EJERCI-││headless)   │
   │       ││      ││       ││       ││       ││CIOS   ││            │
   │BKT    ││FSRS  ││RAG    ││Search ││tree-  ││Zona   ││Ejecuta     │
   │Miscon-││Skill ││Chroma ││+Index ││sitter ││flujo  ││tests       │
   │ception││Tree  ││DB     ││       ││GDScript││       ││captura     │
   └───┬───┘└──┬───┘└───┬───┘└───┬───┘└───┬───┘└───┬───┘└─────┬──────┘
       │       │        │        │        │        │          │
       ▼       ▼        ▼        ▼        ▼        ▼          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        .learnit/ (sistema de archivos)               │
│                                                                      │
│  domain/          student/         pedagogy/       rag/              │
│  ├── kg.json      ├── profile.json ├── strategy.json ├── chroma_db/  │
│  ├── misconceptions.json ├── bkt_state.json ├── effectiveness.json   │
│  └── gen_log.json ├── fsrs_params.json └── session_plan.json         │
│                    ├── affective_log.jsonl                           │
│  sessions/         ├── streak.json     notes/                       │
│  ├── 2026-06-11.json └── review_schedule.json ├── signals.md         │
│  └── analytics.db                  └── concept_index.json            │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.1 Agentes: responsabilidades y disparadores

| Agente | Disparador | Responsabilidad | ¿CCVP? |
|--------|-----------|-----------------|--------|
| **Orquestador** | Cada interacción del usuario | Carga estado, decide subagentes, aplica política, verifica outputs, sintetiza, gestiona ciclo de sesión | Verifica a todos los demás |
| **Diagnosticador** | Post-ejercicio, post-explicación | Actualiza BKT, detecta concepciones erróneas | Sus outputs son verificados por Orquestador |
| **Planificador** | Inicio de sesión, post-concepto | Selecciona siguiente nodo del Skill Tree, programa repasos FSRS | Verificado contra BKT actual |
| **Documentalista** | Cuando se necesita info del dominio | RAG sobre ChromaDB, devuelve chunks + síntesis con fuentes | Chunks grounded, verificables |
| **Buscador Web** | Cuando doc local no cubre o está obsoleta | Busca, extrae, indexa en ChromaDB, devuelve síntesis | Indexado con source tag y fecha |
| **Analizador Código** | Cuando usuario escribe o modifica código | AST vía tree-sitter, detecta patrones, carencias, errores | Output estructurado verificable |
| **Generador Ejercicios** | Cuando Planificador decide práctica | Genera enunciado calibrado a zona de flujo | Dificultad calibrada contra BKT |
| **Ejecutor** | Cuando hay código para probar | Ejecuta Godot headless, captura errores y logs | No-LLM, output determinista |
| **Metacognitivo** | Bajo demanda, fin de sesión | Dashboard, refleja trayectoria, sugiere estrategias de estudio | Datos agregados de analytics |
| **Notero** | Cuando usuario escribe en libreta | Analiza apuntes, vincula a conceptos, detecta concepciones erróneas en notas | Vinculación verificable contra grafo |

### 4.2 Verificación cruzada (CCVP)

Para cada output pedagógico que llegará al usuario, el Orquestador ejecuta:

1. **Grounding check**: ¿Está este contenido respaldado por la documentación indexada? El Documentalista verifica que cada afirmación técnica tenga soporte en fuentes grounded.
2. **Consistency check**: ¿Es consistente con el estado BKT actual del estudiante? El Diagnosticador verifica que no se asuman conocimientos que el usuario no tiene.
3. **Prerequisite check**: ¿El usuario tiene los prerrequisitos para entender este contenido? El Planificador verifica contra el Skill Tree.

Si alguna verificación falla, el Orquestador reformula o descarta el output antes de mostrarlo.

---

## 5. Modelo de dominio: Skill Trees auto-generados

### 5.1 Pipeline de generación

La generación del modelo de dominio es automática y se ejecuta al inicializar un proyecto LearnIt sobre una carpeta.

```
Documentación del ecosistema (HTML/Markdown/PDF)
        │
        ▼
┌─────────────────────────────────┐
│ 1. EXTRACCIÓN E INDEXACIÓN      │
│    MarkdownHeaderTextSplitter   │
│    → Chunks jerárquicos         │
│    → Embeddings vía Jina Code V2│
│    → ChromaDB (parent-child)    │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ 2. IDENTIFICACIÓN DE CONCEPTOS  │
│    LLM extrae:                  │
│    - Entidades (nodos)          │
│    - Relaciones (prerequisiteOf,│
│      relatedTo, partOf)         │
│    - Tipos (declarative,        │
│      procedural, debugging,     │
│      integrative)               │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ 3. INFERENCIA DE PRERREQUISITOS │
│    Señales:                     │
│    - Orden en documentación     │
│    - Marcadores discursivos     │
│    - Dependencias de API        │
│    - Co-ocurrencia en ejemplos  │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ 4. VALIDACIÓN                   │
│    - Baja ambigüedad: automático│
│    - Alta ambigüedad: preguntar │
│      al usuario (1-2 preguntas) │
│    - Rate-distortion: fusionar   │
│      nodos redundantes          │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ 5. CRUCE CON PERFIL DE USUARIO  │
│    - Marcar nodos dominados     │
│      (BKT P > 0.90)            │
│    - Podar sub-árboles conocidos│
│    - Generar rutas de aprendizaje│
└────────────┬────────────────────┘
             ▼
      .learnit/domain/
      ├── knowledge_graph.json
      ├── concept_types.json
      └── misconceptions.json
```

### 5.2 Estructura del Skill Tree

```json
{
  "nodes": {
    "gdscript_variables": {
      "id": "gdscript_variables",
      "label": "Variables en GDScript",
      "type": "declarative",
      "difficulty": 0.20,
      "prerequisites": [],
      "sources": ["docs/gdscript_basics.html#variables"],
      "misconceptions": ["gdscript_dynamic_static_confusion"]
    },
    "character_body_2d": {
      "id": "character_body_2d",
      "label": "CharacterBody2D",
      "type": "declarative",
      "difficulty": 0.45,
      "prerequisites": ["node_hierarchy", "node2d"],
      "sources": ["docs/character_body_2d.html"],
      "misconceptions": ["confuse_characterbody_with_rigidbody"]
    },
    "move_and_slide": {
      "id": "move_and_slide",
      "label": "move_and_slide() y velocity",
      "type": "procedural",
      "difficulty": 0.55,
      "prerequisites": ["character_body_2d", "physics_process", "vector_math"],
      "sources": ["docs/character_body_2d.html#movement"],
      "misconceptions": [
        "velocity_not_normalized",
        "process_instead_of_physics_process",
        "forget_delta_multiply"
      ]
    }
  },
  "edges": [
    {"from": "node_hierarchy", "to": "node2d", "relation": "prerequisiteOf"},
    {"from": "node2d", "to": "character_body_2d", "relation": "prerequisiteOf"},
    {"from": "character_body_2d", "to": "move_and_slide", "relation": "prerequisiteOf"},
    {"from": "physics_process", "to": "move_and_slide", "relation": "prerequisiteOf"}
  ]
}
```

### 5.3 Catálogo de concepciones erróneas

Cada entrada del catálogo especifica:

- **Descripción precisa** de la concepción errónea
- **Patrón de detección** (AST, output de ejecución, o respuesta del usuario)
- **Estrategia de corrección** (contraste explícito, ejemplo donde la diferencia es visible, o ejercicio de refutación)
- **Indicador BKT**: cómo se ajusta P(know) cuando se detecta

Ejemplo:

```json
{
  "id": "process_instead_of_physics_process",
  "description": "El estudiante cree que _process() y _physics_process() son intercambiables para código de física y movimiento.",
  "detection": "Llamada a move_and_slide() dentro de _process() en lugar de _physics_process()",
  "correction_strategy": "Contraste explícito con ejemplo donde el frame rate variable produce movimiento inconsistente en _process()",
  "bkt_impact": "P_slip aumenta a 0.40 para el concepto move_and_slide"
}
```

---

## 6. Modelo del estudiante

### 6.1 Bayesian Knowledge Tracing (BKT)

Para cada skill en el grafo de dominio se mantienen cuatro parámetros:

| Parámetro | Significado | Inicialización |
|-----------|-------------|----------------|
| P(L₀) | Probabilidad inicial de que el usuario ya sepa la skill | Estimada del perfil (ej: astrofísico con Python avanzado → P(L₀) alto para variables, bajo para nodos Godot) |
| P(T) | Probabilidad de aprender la skill en un paso | 0.30 por defecto, se ajusta con datos |
| P(S) | Probabilidad de slip (error aunque sepas) | 0.10 por defecto |
| P(G) | Probabilidad de guess (acierto sin saber) | 0.15 por defecto |

Tras cada ejercicio, el Diagnosticador actualiza:

```
P(Lₙ | evidencia) = P(Lₙ₋₁) * P(transición) + (1 - P(Lₙ₋₁)) * P(T)

Si acierto: P(evidencia | L) = (1 - P(S)) / ((1 - P(S)) + P(G))
Si error:   P(evidencia | ¬L) = P(S) / (P(S) + (1 - P(G)))
```

### 6.2 FSRS (Free Spaced Repetition Scheduler)

Paralelo al BKT, cada skill tiene un estado en FSRS con tres variables de memoria:

- **Dificultad (D)**: qué tan difícil es la skill para este usuario específico
- **Estabilidad (S)**: tiempo que el usuario retiene la skill tras un repaso
- **Recuperabilidad (R)**: probabilidad de recordar la skill en un momento dado

FSRS programa repasos automáticos. El Planificador consulta `review_schedule.json` al inicio de cada sesión y prioriza las skills cuya R ha caído por debajo del umbral (típicamente R < 0.80). Tras cada interacción con una skill, recalcula S y D, y agenda la próxima revisión.

### 6.3 Perfil del usuario

```json
{
  "user_id": "astrofisico_01",
  "background": {
    "profession": "Astrofísico",
    "programming": {"python": 0.95, "cpp": 0.60, "gdscript": 0.0},
    "domains": ["physics", "data_analysis", "simulation"],
    "learning_style": "analytical",
    "preferred_pace": "moderate"
  },
  "current_project": "godot_platformer",
  "project_goal": "Crear un juego de plataformas 2D con físicas personalizadas",
  "session_preferences": {
    "mode": "auto_detect",
    "max_sessions_per_day": 3,
    "min_gap_minutes": 120,
    "default_duration_minutes": 50,
    "intensive_duration_minutes": 40,
    "third_session_concept_new": false,
    "optimal_hours": [],
    "low_performance_hours": [],
    "weekly_availability": {
      "monday": 1, "tuesday": 1, "wednesday": 1,
      "thursday": 1, "friday": 1, "saturday": 3, "sunday": 2
    }
  },
  "learned_patterns": {
    "best_session_duration": null,
    "fatigue_onset_minute": null,
    "second_session_penalty": null,
    "third_session_penalty": null
  }
}
```

### 6.4 Modelo afectivo ligero

Sin acceso a cámara ni sensores, el modelo afectivo infiere el estado del usuario a partir de señales textuales y patrones de comportamiento:

| Señal | Indicador | Umbral de acción |
|-------|-----------|------------------|
| Tasa de error creciente | Fatiga cognitiva | > +15% vs baseline del estudiante |
| Tiempo de respuesta creciente | Fatiga o confusión | > 2x mediana de la sesión |
| Respuestas más cortas | Desenganche | < 50% longitud media del usuario |
| Preguntas de confirmación frecuentes | Inseguridad | > 30% de mensajes contienen "¿es correcto?", "¿está bien?" |
| Lenguaje negativo | Frustración | "no entiendo nada", "esto es imposible", "qué mal" |

Estas señales alimentan el estado afectivo (`affective_log.jsonl`) y son consultadas por el Orquestador para decidir cambios de estrategia, pausas adicionales, o cierre de sesión.

### 6.5 Historial de concepciones erróneas

```json
{
  "student_id": "astrofisico_01",
  "history": [
    {
      "misconception_id": "process_instead_of_physics_process",
      "detected_at": "2026-06-11T18:30:00Z",
      "concept": "move_and_slide",
      "evidence": "Usaste _process(delta) en lugar de _physics_process(delta) para move_and_slide()",
      "corrected": true,
      "correction_date": "2026-06-11T18:45:00Z",
      "recurrence_count": 0
    }
  ]
}
```

El Diagnosticador detecta recurrencias. Si una concepción errónea recurre más de dos veces, el Orquestador escala la estrategia de corrección (de contraste explícito a ejercicio de refutación dedicado).

---

## 7. Modelo pedagógico

### 7.1 Mapeo tipo-concepto → estrategia

| Tipo de concepto | Estrategia por defecto | Ejemplo en Godot |
|-----------------|----------------------|------------------|
| **Declarative** (qué es X) | Ejemplo comentado + verificación | "CharacterBody2D es un nodo que..." → "Explícame con tus palabras qué lo diferencia de RigidBody2D" |
| **Procedural** (cómo se hace X) | Scaffolding progresivo + ejercicio | "Paso 1: crea la escena. Paso 2: añade CharacterBody2D. Paso 3: escribe el script..." → "Ahora hazlo tú para el enemigo" |
| **Debugging** (qué falla y por qué) | Socrático | "Tu personaje no se mueve. ¿En qué método debería estar move_and_slide()? ¿Por qué?" |
| **Integrative** (combina A y B) | Intercalado + mini-proyecto | "Combina movimiento con animaciones: el personaje debe cambiar de sprite al moverse en cada dirección" |
| **Misconception** (error conocido) | Contraste explícito | "_process se llama cada frame de renderizado; _physics_process cada frame de física. Aquí tienes un ejemplo donde la diferencia importa..." |

Este mapeo es genérico y reusable para cualquier dominio. Lo que cambia entre proyectos es el contenido del grafo, no las estrategias.

### 7.2 Q-table de estrategia

El Orquestador mantiene una política que aprende qué estrategia funciona mejor para qué situación:

```
Estado:  (concept_type, P_know, affective_state, session_number, hour_of_day)
Acción:  (strategy, scaffolding_level, pace)
Recompensa: Δ P_know en la siguiente evaluación del concepto
```

Con suficientes interacciones, la Q-table converge a preferencias personalizadas. Por ejemplo, puede aprender que para este usuario los conceptos procedurales se aprenden mejor con scaffolding nivel 2 por la mañana, pero con nivel 1 por la noche.

### 7.3 Bucle continuo de mejora

```
Sesión N
  → Orquestador selecciona estrategia según Q-table
  → Diagnosticador mide resultado (Δ BKT)
  → Recompensa calculada
  → Q-table actualizada
  → Session N+1 usa política mejorada
```

No hay un chequeo periódico de "metodología correcta". La optimización es continua y basada en evidencia del aprendizaje real del usuario.

---

## 8. Modelo de sesión: estructura, ritmo y adaptabilidad

### 8.1 Ciclo estándar de sesión (~45-50 minutos)

```
┌──────────────────────────────────────────────────────┐
│                 learnit (inicio de sesión)            │
│                                                       │
│  - Orquestador carga perfil + estado                  │
│  - Planificador selecciona siguiente concepto         │
│  - Se muestra racha actual + progreso del proyecto    │
│  - Si hay sesión programada y se llegó tarde:         │
│    pregunta y ajusta (ver sección 9)                  │
│  - Si no hay sesión programada (acceso espontáneo):   │
│    "¿Sesión completa (~45 min) o rápida (~20 min)?"   │
│  - "Hoy: CharacterBody2D y move_and_slide()"          │
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│                 Enseñanza                             │
│  - Documentalista recupera chunks relevantes          │
│  - Orquestador explica con estrategia adecuada        │
│  - Usuario interactúa, pregunta, toma notas           │
│  - Notero analiza apuntes y los vincula a conceptos   │
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│         Pausa metacognitiva (~12 min)                 │
│  - Overlay suave: "Pausa de 30s"                     │
│  - "¿Qué acabas de aprender? ¿Qué te confunde?"       │
│  - Usuario escribe en libreta                         │
│  - Notero analiza respuesta y detecta misconceptions  │
│  - No es opcional                                     │
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│                 Ejercicio                             │
│  - Generador crea ejercicio calibrado a zona de flujo │
│  - Usuario escribe código en su editor                │
│  - Analizador revisa AST (tree-sitter)                │
│  - Ejecutor corre Godot headless                      │
│  - Diagnosticador actualiza BKT                       │
│  - Orquestador da feedback (sin dar la solución)      │
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│         Pausa metacognitiva (~25 min)                 │
│  - "Explica con tus palabras qué hace move_and_slide" │
│  - Notero analiza y compara con la explicación experta│
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│                 Cierre de sesión                      │
│  - Orquestador monitorea señales de fatiga            │
│  - Si tiempo > 45 min o tasa error > +15% baseline:   │
│    sugiere cierre activo razonado                     │
│  - Metacognitivo muestra dashboard de sesión          │
│  - Planificador agenda próxima sesión                 │
│  - Negociación de horario (sección 9)                 │
│  - "¿Mañana a las 18:00? Tu racha es de 5 días."     │
└──────────────────────────────────────────────────────┘
```

### 8.2 Modos de intensidad

El sistema se adapta a la disponibilidad del usuario. La investigación muestra que **múltiples sesiones cortas con gaps > 2 horas** son superiores a sesiones largas, y muy superiores a sesiones maratónicas.

| Modo | Sesiones/día | Duración c/u | Gap mínimo | Concepto nuevo en 3ª sesión | ¿Cuándo? |
|------|-------------|-------------|------------|---------------------------|----------|
| **Estándar** | 1 | 45-50 min | N/A | Sí | Día laboral típico |
| **Intensivo** | 2-3 | 40-45 min | 2 horas | No en 3ª sesión (solo repasos + ejercicios) | Verano, bootcamp |
| **Libre** | 1-2 | Flexible, máx 50 min | Flexible | Sí en 1ª, no en 2ª | Fin de semana |
| **Express** | 1 | 15-25 min | N/A | No (solo repasos o ejercicio ligero) | Día con poco tiempo |

Al inicio de cada sesión, el Orquestador pregunta o infiere la disponibilidad:

```
┌─────────────────────────────────────────┐
│  ¿Cuánto tiempo tienes hoy?             │
│                                         │
│  ( ) ~45 min — sesión estándar          │
│  ( ) ~90 min — 2 sesiones con descanso  │
│  ( ) ~20 min — sesión express           │
│  ( ) Sin plan fijo — tú guías           │
└─────────────────────────────────────────┘
```

### 8.3 Micro-pausas forzadas

- Cada ~12 minutos de interacción activa
- 30 segundos de duración
- **No opcionales** (Biwer et al., 2023: las pausas auto-reguladas son menos efectivas que las sistemáticas)
- Componente metacognitivo obligatorio: "¿Qué acabo de aprender? ¿Qué me confunde? Escríbelo en la libreta."
- El Notero analiza la respuesta del usuario y detecta posibles concepciones erróneas incluso en las pausas

### 8.4 Terminación activa de sesión

El Orquestador monitoriza y sugiere cierre activo cuando se supera alguno de estos umbrales:

| Condición | Umbral | Mensaje |
|-----------|--------|---------|
| Tiempo de sesión | > 45 min (advertencia) | "Llevas 45 minutos. ¿Cerramos en 5 min?" |
| Tiempo de sesión | > 52 min (sugerencia) | "Has estado 52 minutos. Es buen momento para cerrar." |
| Tasa de error | > +15% vs baseline | "Tu tasa de acierto ha bajado del 82% al 61%. La fatiga puede estar afectando. ¿Cerramos?" |
| Tiempo de respuesta | > 2x mediana de sesión | "Estás tardando más en responder. ¿Necesitas un descanso?" |
| Señales de fatiga en lenguaje | Respuestas < 50% longitud media | "Noto que tus respuestas son más cortas. ¿Seguimos mañana?" |

El cierre es **sugerido y razonado**, no impuesto. El sistema explica por qué es mejor parar usando datos concretos de la sesión.

### 8.5 Sistema de rachas (streaks)

Basado en el RCT de Aulagnon et al. (2024) con 60,000 estudiantes:

- Rachas visibles en la UI (barra superior)
- Hitos celebrados: 7, 14, 30, 100 días
- 2 "freezes" por semana que permiten mantener la racha si se falta un día
- Al romper la racha: sin castigo, mensaje de ánimo, y sugerencia de mini-sesión de 15 minutos para retomar
- La investigación muestra que **no hay efecto de desánimo** al romper una racha — los usuarios no se desconectan más tiempo tras romperla

---

## 9. Negociación de horario y gestión de asistencia

LearnIt negocia horarios de sesión con el usuario y gestiona los casos de impuntualidad, cancelación y acceso espontáneo. Toda esta interacción ocurre dentro de la interfaz web, sin depender de canales externos como correo electrónico. El correo se contempla como funcionalidad extra opcional para recordatorios y estadísticas, pero no es requisito para la negociación de sesiones.

### 9.1 Configuración inicial de horario

Al crear el proyecto o en cualquier momento desde la configuración:

```
┌──────────────────────────────────────────────┐
│  LearnIt — Configuración de horario          │
│                                              │
│  ¿Qué días prefieres estudiar?               │
│  [✓] L  [✓] M  [✓] X  [✓] J  [✓] V         │
│  [ ] S  [ ] D                                │
│                                              │
│  Franja horaria preferida:                   │
│  [18:00] — [19:00]  (WEST)                  │
│                                              │
│  Duración por sesión:                        │
│  ( ) 30 min  (•) 45 min  ( ) 60 min         │
│                                              │
│  Flexibilidad:                               │
│  (•) Preguntar cada día si mantengo la hora  │
│  ( ) Horario fijo, avisarme solo si cambio   │
│                                              │
│  [Guardar]                                   │
└──────────────────────────────────────────────┘
```

### 9.2 Negociación al final de cada sesión

Al terminar una sesión, el Orquestador propone la siguiente:

```
┌──────────────────────────────────────────────┐
│  Sesión completada — 47 min                  │
│                                              │
│  ¿Seguimos mañana?                           │
│  Día: viernes 12 de junio                    │
│  Hora propuesta: 18:00 WEST                  │
│  Concepto: Señales (signals)                 │
│                                              │
│  (•) Sí, a las 18:00                         │
│  ( ) Sí, pero a otra hora: [____]            │
│  ( ) Mañana no puedo, saltemos al sábado     │
│  ( ) No lo sé aún — confirmo mañana          │
│                                              │
│  [Confirmar]                                 │
└──────────────────────────────────────────────┘
```

### 9.3 Escenarios de impuntualidad

#### Escenario A: El usuario llega tarde a una sesión programada

```
18:00 — Hora programada
18:12 — Usuario abre LearnIt

El Orquestador detecta que había una sesión programada a las 18:00:

┌──────────────────────────────────────────────┐
│  Tenías una sesión programada a las 18:00.   │
│  Llegas 12 minutos tarde.                    │
│                                              │
│  ¿Qué quieres hacer?                         │
│                                              │
│  (•) Empezar ahora — sesión acortada (~33 min)│
│      Hoy solo repasos y ejercicios           │
│  ( ) Reprogramar para mañana                 │
│  ( ) Sesión express (15 min) y mañana normal │
│                                              │
│  Tu racha no se ve afectada por llegar tarde.│
└──────────────────────────────────────────────┘
```

Si elige empezar ahora, el Planificador ajusta la sesión: omite concepto nuevo, prioriza repasos FSRS y un ejercicio ligero. La duración se acorta proporcionalmente. La racha se mantiene.

#### Escenario B: El usuario abre el programa fuera de su horario habitual

```
Sábado 15:30 — No hay sesión programada (el usuario estudia de lunes a viernes)

┌──────────────────────────────────────────────┐
│  ¡Hola! No tenías sesión programada hoy.     │
│                                              │
│  ¿Qué te trae por aquí?                      │
│                                              │
│  (•) Quiero una sesión ahora                 │
│      ─ ¿Completa (~45 min) o express (~20)?  │
│  ( ) Solo quiero revisar mis apuntes         │
│  ( ) Quiero replanificar mis sesiones        │
│  ( ) Solo mirar el dashboard                 │
└──────────────────────────────────────────────┘
```

Si elige replanificar, el Orquestador inicia un diálogo para ajustar la configuración de horario. Si elige sesión, se trata como sesión en modo libre.

#### Escenario C: El usuario falta a una sesión y no avisó

```
Viernes 18:00 — Sesión programada
Viernes 23:59 — El usuario no ha abierto LearnIt en todo el día

Sábado 10:00 — El usuario abre LearnIt

┌──────────────────────────────────────────────┐
│  Ayer tenías una sesión programada a las     │
│  18:00 y no llegaste.                        │
│                                              │
│  ¿Qué pasó?                                  │
│                                              │
│  ( ) No pude — usemos un freeze              │
│  ( ) Me olvidé — sin problema, seguimos      │
│  ( ) Quiero ajustar mi horario semanal       │
│                                              │
│  Racha actual: 4 días (usando 1 freeze)      │
└──────────────────────────────────────────────┘
```

El sistema no castiga. Si el usuario usa un freeze, la racha se mantiene. Si no, la racha se reinicia pero con mensaje de ánimo y sugerencia de mini-sesión para retomar impulso.

### 9.4 Ajuste fino automático de patrones

Con el tiempo, el sistema aprende patrones del usuario y ajusta sus sugerencias:

- Si el usuario consistentemente rinde peor en sesiones de viernes por la tarde, el Planificador sugiere mover la sesión del viernes a otra franja o hacerla más ligera.
- Si el usuario falta varios lunes seguidos, el Orquestador pregunta si quiere cambiar la disponibilidad de ese día.
- Si el usuario hace sesiones dobles los sábados espontáneamente, el perfil se actualiza: `weekly_availability.saturday` pasa a 3.

Estos ajustes se reflejan en `learned_patterns` dentro del perfil.

---

## 10. Arquitectura multi-agente con verificación cruzada

### 10.1 Por qué multi-agente a pesar de la tasa de fallo del 41-86.7%

El estudio MAST (Cemri et al., NeurIPS 2025) identificó que los fallos en sistemas multi-agente provienen de tres causas raíz. LearnIt las neutraliza en el diseño:

| Causa de fallo | Mitigación en LearnIt |
|---------------|----------------------|
| **Ambigüedad de especificación** (agentes con responsabilidades solapadas) | Cada agente tiene un contrato explícito: input schema, output schema, herramientas permitidas, y disparador único |
| **Desalineación entre agentes** (handoffs no estructurados) | El Orquestador es el único punto de handoff. Los subagentes no se comunican entre sí |
| **Verificación de tareas ausente** (errores que se propagan) | CCVP obligatorio: todo output de subagente es verificado antes de llegar al usuario |

### 10.2 Contratos de subagentes

Cada subagente tiene un contrato formal que define su entrada, salida y restricciones:

**Ejemplo: Documentalista**

```
INPUT:
  - query: string
  - concepts: string[] (IDs del grafo relacionados)
  - student_bkt: {concept_id: P_know} (para no explicar lo ya sabido)

OUTPUT:
  - chunks: [{text, source, relevance_score}]
  - synthesis: string (2-3 párrafos)
  - confidence: 0-1
  - sources_checked: int

RESTRICCIONES:
  - Solo usa ChromaDB local. No accede a internet.
  - Si confidence < 0.7, el Orquestador decide si invocar al Buscador Web.
  - Cada afirmación técnica debe tener source anclado.
```

**Ejemplo: Diagnosticador**

```
INPUT:
  - exercise_id: string
  - user_solution: {code, execution_result, errors}
  - expected_behavior: string
  - concepts_involved: string[]

OUTPUT:
  - bkt_updates: {concept_id: {P_know_old, P_know_new, evidence_type}}
  - misconceptions_detected: [{misconception_id, confidence, evidence}]
  - flow_zone: {P_correct_estimated, zone: "flow"|"boredom"|"anxiety"}
  - recommendation: "continue"|"review"|"scaffold"|"move_on"

RESTRICCIONES:
  - No accede a documentación externa. Solo opera sobre estado BKT y catálogo misconceptions.
  - Si detecta un patrón no catalogado, lo registra como unknown_misconception para revisión futura.
```

### 10.3 Flujo multi-agente en una interacción típica

```
Usuario: "No entiendo por qué el personaje no se mueve."

Orquestador:
  1. Evalúa si necesita más contexto → sí
  2. Invoca AnalizadorCódigo (lee character.gd)
  3. Recibe: "move_and_slide() llamado en _process(), no en _physics_process()"
  4. CCVP Grounding → Documentalista confirma que move_and_slide() debe ir en _physics_process()
  5. CCVP Consistency → Diagnosticador confirma que el usuario tiene BKT alto en _process 
     pero bajo en _physics_process → concepción errónea detectada
  6. CCVP Prerequisite → Planificador confirma que el usuario ya cubrió node_hierarchy y node2d
  7. Selecciona estrategia "contraste explícito" (tipo misconception)
  8. Sintetiza respuesta:

     "Buena pregunta. He revisado tu código y veo que llamas a move_and_slide() 
     dentro de _process(). Este es un error muy común. _process() se ejecuta 
     cada frame de renderizado — si tu juego va a 144 FPS, se llama 144 veces 
     por segundo. _physics_process() se ejecuta a frecuencia fija (60 Hz por 
     defecto), diseñada para física y movimiento.
     
     Mira este ejemplo donde la diferencia se nota: [código de contraste]
     
     ¿Quieres intentar mover move_and_slide() a _physics_process() y ejecutamos 
     de nuevo?"
```

---

## 11. Interfaz: CLI launcher + web local

### 11.1 CLI como gestor de ciclo de vida

La CLI no es la interfaz de aprendizaje. Es el punto de entrada y control del programa:

```
$ learnit                      # Inicia el servidor web y abre el navegador
$ learnit --update             # Actualiza LearnIt a la última versión
$ learnit stop                 # Detiene el servidor web
$ learnit status               # Muestra estado rápido (próxima sesión, racha, progreso)
$ learnit config               # Abre configuración en el navegador
```

Al ejecutar `learnit` sin argumentos, el programa:
1. Levanta un servidor HTTP + WebSocket en `localhost:7823`
2. Abre el navegador del sistema en esa URL
3. Carga el estado desde `.learnit/`
4. Muestra la interfaz de sesión

### 11.2 Web local: tres paneles

La interfaz web está construida con SolidJS y Tailwind CSS. Es una SPA ligera que se comunica con el backend Go vía WebSocket para streaming de respuestas y actualizaciones en tiempo real.

```
┌──────────────────────────┬──────────────────────────────┐
│                          │                              │
│    CHAT                  │    LIBRETA                   │
│    (~60% width)          │    (~40% width)              │
│                          │                              │
│  ┌────────────────────┐  │  ┌────────────────────────┐  │
│  │ [Orquestador]      │  │  │ Mis apuntes sobre      │  │
│  │ Hoy vamos a ver    │  │  │ CharacterBody2D        │  │
│  │ CharacterBody2D... │  │  │                        │  │
│  │                    │  │  │ - Hereda de Node2D     │  │
│  │ [Tú]               │  │  │ - Tiene velocity como  │  │
│  │ Vale, entiendo...  │  │  │   vector de estado     │  │
│  │                    │  │  │ - move_and_slide() se  │  │
│  │ [Orquestador]      │  │  │   aplica cada frame    │  │
│  │ Exacto. Ahora haz   │  │  │   físico              │  │
│  │ este ejercicio...   │  │  │ - ¡Ojo! Usar _physics_ │  │
│  │                    │  │  │   process, no _process │  │
│  └────────────────────┘  │  └────────────────────────┘  │
│                          │                              │
│  ┌─────────────────────┐ │  Vinculado a:                │
│  │ Escribe aquí...     │ │  ✓ character_body_2d         │
│  └─────────────────────┘ │  ✓ move_and_slide            │
│                          │  ✓ physics_process           │
├──────────────────────────┴──────────────────────────────┤
│  BARRA SUPERIOR                                         │
│  Racha: 5 días  |  Sesión: 32 min  |  Zona: flow        │
└─────────────────────────────────────────────────────────┘
```

La libreta está vinculada al modelo de dominio: cada apunte se asocia automáticamente a los conceptos del grafo mediante similitud semántica. El Notero analiza el contenido de los apuntes y puede detectar concepciones erróneas incluso en las notas personales.

### 11.3 Dashboard post-sesión

Al finalizar cada sesión, el Metacognitivo muestra un resumen:

```
┌──────────────────────────────────────────────┐
│  Sesión completada — 47 min                  │
│                                              │
│  CONCEPTOS TRABAJADOS:                       │
│  ✓ CharacterBody2D       P: 0.30 → 0.55     │
│  ✓ move_and_slide()      P: 0.25 → 0.48     │
│  → En progreso: Señales                     │
│                                              │
│  EJERCICIOS: 2/2 completados                 │
│  Tasa de acierto: 78%                        │
│  Zona de flujo: 68% del tiempo               │
│                                              │
│  CONCEPCIONES ERRÓNEAS DETECTADAS:           │
│  ✗ _process vs _physics_process (corregida) │
│                                              │
│  REPASOS PENDIENTES (FSRS):                  │
│  • node_hierarchy — en 3 días                │
│  • gdscript_signals — mañana                 │
│                                              │
│  [Continuar]                                 │
└──────────────────────────────────────────────┘
```

---

## 12. Stack técnico

| Capa | Tecnología | Justificación |
|------|-----------|---------------|
| **LLM (todos los agentes)** | DeepSeek V4 Pro Max | Máxima capacidad de razonamiento, ventana de 1M tokens, presupuesto disponible |
| **Backend** | Go | Concurrencia nativa (goroutines), binario único, HTTP + WebSocket en stdlib, sin dependencias externas |
| **Frontend** | SolidJS + Tailwind CSS | Reactividad sin virtual DOM, señales nativas, SPA ligera, sin build step complejo |
| **CLI launcher** | Go (flags stdlib o Cobra) | `learnit`, `learnit --update`, `learnit stop`, `learnit status` |
| **Embeddings** | Jina Code V2 (Apache 2.0) | Específico de código, late chunking, open source, ejecutable local |
| **Vector Store** | ChromaDB (modo servidor local) | HTTP REST, sin dependencia de lenguaje específico, parent-child retrieval |
| **RAG Framework** | ParentDocumentRetriever (LangChain o implementación propia en Go) | Splitting recursivo 400/1000 tokens, 10% overlap |
| **AST Parser** | tree-sitter-gdscript (binding Go) | Chunking sintáctico del código del usuario, detección de patrones |
| **FSRS** | Algoritmo FSRS v6 implementado en Go | ~500 líneas, sin dependencias, 17 parámetros por usuario |
| **Base de datos** | SQLite (mattn/go-sqlite3) | Nativo en Go, sin servidor, analytics + estado estructurado |
| **Persistencia** | JSON (archivos planos) + SQLite | JSON para archivos editables por el usuario, SQLite para consultas y métricas |
| **WebSocket** | gorilla/websocket o nhooyr.io/websocket | Streaming de respuestas LLM en tiempo real |
| **Ejecución Godot** | `godot --headless` | Ejecución de tests y captura de errores |

---

## 13. Estructura de `.learnit/`

```
proyecto-godot/
├── AGENTS.md                          # Estándar abierto (compatible con Codex, Cursor, Copilot)
├── .learnit/
│   ├── config.json                    # Config global: proyecto, comunicador, preferencias
│   ├── domain/
│   │   ├── knowledge_graph.json       # Skill Tree con nodos y prerequisiteOf
│   │   ├── concept_types.json         # declarative | procedural | debugging | integrative
│   │   ├── misconceptions.json        # Catálogo de concepciones erróneas conocido
│   │   └── generation_log.json        # Trazabilidad: cómo y cuándo se generó cada nodo
│   ├── student/
│   │   ├── profile.json               # Background, intereses, proyecto, preferencias de horario
│   │   ├── bkt_state.json             # Por skill: P(L₀), P(T), P(S), P(G), P_know actual
│   │   ├── fsrs_params.json           # 17 parámetros personales del scheduler
│   │   ├── review_schedule.json       # Próximos repasos programados por skill
│   │   ├── misconception_history.json # Errores detectados, corregidos, recurrentes
│   │   ├── affective_log.jsonl        # {timestamp, flow_zone, fatigue_signals, intervention}
│   │   └── streak.json                # {current, longest, freezes_used, freezes_max, history}
│   ├── pedagogy/
│   │   ├── strategy_map.json          # Tipo-concepto → estrategia por defecto
│   │   ├── strategy_effectiveness.json# Q-table: (estado, acción) → recompensa esperada
│   │   └── session_plan.json          # Plan de la sesión actual o próxima
│   ├── rag/
│   │   ├── chroma_db/                 # Vector store parent-child con toda la documentación
│   │   └── index_meta.json            # Fuentes indexadas, versiones, fechas
│   ├── sessions/
│   │   ├── 2026-06-11T18-00.json      # Traza completa de interacción de la sesión
│   │   └── analytics.db               # SQLite con métricas agregadas
│   └── notes/
│       ├── 2026-06-11_signals.md      # Apunte del usuario vinculado a conceptos
│       └── concept_index.json         # Mapa bidireccional: apunte ↔ concepto del grafo
```

---

## 14. Qué hace a LearnIt mejor que el SOTA actual

### 14.1 Diferenciadores arquitectónicos

| Aspecto | SOTA actual | LearnIt |
|---------|-------------|---------|
| **Modelo de dominio** | Manual por expertos, o KG no validado | Auto-generado desde documentación con validación de baja ambigüedad, podado por perfil |
| **Modelo de estudiante** | Overlay binario o basado en prompts | BKT (4 params/skill) + FSRS (17 params/user) + misconception history + affective log |
| **Pedagogía** | Prompt engineering frágil | Q-table aprendida por usuario, mapeo tipo-concepto → estrategia, bucle continuo de mejora |
| **Verificación** | RAG sin verificación o verificación manual | CCVP obligatorio: grounding + consistency + prerequisite check en cada output |
| **Sesión** | Chat abierto sin estructura ni límites | Ciclo con ritmo pedagógico, pausas metacognitivas forzadas, cierre activo basado en fatiga |
| **Hábito** | Ignorado en investigación ITS | Rachas con freezes, negociación de horario, adaptación a disponibilidad |
| **Gestión de asistencia** | Inexistente | Negociación de horario, detección de impuntualidad, sesiones acortadas, replanificación |
| **Multi-agente** | 41-86.7% fallo por descoordinación | Contratos explícitos, handoff único, verificación cruzada, sin comunicación directa entre subagentes |
| **Cognitive offloading** | Documentado y no mitigado | Modo socrático por defecto, pausas metacognitivas, nunca solución sin razonamiento previo |
| **Portabilidad** | Dependiente de plataforma/LMS | Carpeta `.learnit/` versionable con git, shareable, `AGENTS.md` interoperable |
| **Stack** | Python monolítico o SaaS cloud | Go + SolidJS, binario único, web local, sin dependencia de servicios externos |

### 14.2 Lo que LearnIt hace que ningún otro sistema hace (junio 2026)

1. **Skill Tree auto-generado desde la documentación del proyecto del usuario, podado por su perfil.** MMKG-RAG genera grafos desde documentos, pero no los poda contra el perfil del estudiante ni los enfoca a un proyecto concreto.

2. **BKT + FSRS integrados en un tutor conversacional con LLM.** Los sistemas de knowledge tracing son motores de predicción, no tutores conversacionales. Los tutores conversacionales no tienen BKT ni FSRS. LearnIt une ambas tradiciones.

3. **Verificación cruzada obligatoria (CCVP) en cada output pedagógico.** Ningún sistema SOTA implementa CCVP como requisito arquitectónico. La verificación existe como opción de despliegue, no como constraint de diseño.

4. **Ciclo de sesión completo con pausas metacognitivas forzadas, cierre activo por fatiga, y negociación de horario.** Los sistemas actuales o son chat abierto sin estructura, o plataformas rígidas sin negociación.

5. **Gestión de impuntualidad y acceso espontáneo con ajuste dinámico del plan de sesión.** Si llegas 12 minutos tarde, el sistema acorta la sesión proporcionalmente, omite el concepto nuevo, y prioriza repasos. Nadie más hace esto.

6. **Portabilidad total en `.learnit/` como fuente de verdad.** Ni un solo sistema SOTA es portable entre entornos. LearnIt es una carpeta que viaja con tu proyecto.

7. **Modos de intensidad adaptados a la disponibilidad del usuario**, con la investigación sobre espaciado como fundamento (más sesiones con gaps > mejor que sesiones más largas). El sistema guía activamente hacia la distribución óptima.

---

## 15. Hoja de ruta

### Fase 1: Fundación (semanas 1-4)
- `learnit` inicia servidor web, abre navegador
- Indexación de documentación (Godot) en ChromaDB con parent-child retrieval
- Chat funcional con Orquestador (agente único inicialmente)
- RAG básico vía Documentalista
- Estructura `.learnit/` generada al iniciar proyecto
- Perfil de usuario inicial
- Persistencia de sesiones en JSON

### Fase 2: Skill Tree y diagnóstico (semanas 5-8)
- Pipeline de generación automática de Skill Tree desde docs
- Cruce con perfil de usuario: podar conceptos dominados
- BKT funcional con 4 parámetros por skill
- Catálogo inicial de concepciones erróneas
- Diagnosticador como subagente separado
- Planificador con recorrido DFS inverso sobre Skill Tree
- FSRS integrado con programación de repasos
- CCVP básico (grounding check)

### Fase 3: Pedagogía y ejercicios (semanas 9-12)
- Q-table de estrategia pedagógica
- Mapeo tipo-concepto → estrategia
- Generador de ejercicios calibrados a zona de flujo
- Analizador de código con tree-sitter-gdscript
- Ejecutor (Godot headless) con captura de errores
- Notero: análisis de apuntes y vinculación a conceptos
- Pausas metacognitivas forzadas
- Dashboard post-sesión básico

### Fase 4: Sesión, hábito y negociación (semanas 13-16)
- Rachas con freezes
- Cierre activo de sesión basado en fatiga
- Negociación de horario al final de sesión
- Gestión de impuntualidad (detección, sesión acortada, replanificación)
- Gestión de acceso espontáneo (sesión no programada)
- Modos de intensidad (estándar, intensivo, libre, express)
- Subagente Metacognitivo con dashboard completo
- UI web completa (SolidJS): chat, libreta vinculada, dashboard

### Fase 5: Pulido y SOTA+ (semanas 17-20)
- CCVP completo (grounding + consistency + prerequisite)
- Buscador Web con indexación automática en ChromaDB
- Rate-distortion para poda de nodos redundantes en el grafo
- Analytics avanzados (SQLite)
- `AGENTS.md` auto-generado desde `.learnit/student/profile.json`
- Correo electrónico opcional (recordatorios, estadísticas semanales)
- Pruebas con múltiples dominios (Godot, Rust, astrofísica computacional)
- Ajuste fino automático de patrones de aprendizaje

---

## 16. Métricas de éxito

### 16.1 Métricas de aprendizaje

| Métrica | Definición | Objetivo |
|---------|-----------|----------|
| Δ BKT medio por sesión | Incremento promedio de P(know) en skills objetivo | > +0.15 |
| Transferencia sin asistencia | Desempeño en ejercicio sin ayuda del tutor | > 70% del desempeño asistido |
| Retención a 7 días (FSRS) | Skills con R > 0.80 tras 7+ días de aprendidas | > 85% |
| Concepciones erróneas corregidas | % de misconceptions detectadas que no recurren en 30 días | > 80% |

### 16.2 Métricas de engagement

| Métrica | Definición | Objetivo |
|---------|-----------|----------|
| Días consecutivos (racha) | Días con sesión completada (incluyendo freezes) | > 5 media |
| Tasa de abandono de sesión | Sesiones terminadas por cierre normal vs abandono | > 90% |
| Zona de flujo | % de ejercicios con P(correct) ∈ [0.40, 0.70] | > 60% |
| Tiempo en zona de flujo | Minutos en flow vs total de sesión | > 70% |
| Adherencia a horario | Sesiones iniciadas en franja ±15 min de lo programado | > 75% |

### 16.3 Métricas de sistema

| Métrica | Definición | Objetivo |
|---------|-----------|----------|
| Precisión CCVP | Outputs que pasan verificación en primer intento | > 85% |
| Tasa de alucinación | Contenidos no respaldados por fuentes grounded | < 3% |
| Latencia de respuesta | Tiempo desde input hasta primer token visible | < 3s (streaming) |
| Fallos multi-agente | Invocaciones con error de coordinación | < 5% (vs 41-86.7% SOTA) |
| Precisión del Skill Tree | Nodos y aristas validados como correctos (automático + usuario) | > 90% |

---

## 17. Referencias

1. Chu et al., "LLM Agents for Education: Advances and Applications", 2025. arXiv:2503.11733
2. Zerkouk et al., "A Comprehensive Review of AI-based ITS", 2025. arXiv:2507.18882
3. Márquez-Carpintero et al., "Simulation of teaching behaviours in ITS", *Artificial Intelligence Review*, 2026
4. Cemri et al., "Why Do Multi-Agent LLM Systems Fail?", *NeurIPS 2025*
5. Deng & Yuan, "ITS Based on Automatic Multimodal Knowledge Graphs and RAG", *Frontiers in Computer Science*, 2026
6. "Deep Learning Based Knowledge Tracing in ITS" (MSKT), *Nature Scientific Reports*, 2025
7. "Next Token Knowledge Tracing" (NTKT), arXiv:2511.02599, 2025
8. "SkillTree: Scalable Personalized Learning with LLM-Linked Custom Knowledge Graphs", IES 2025-2026
9. "Graph4Learn: Evolving Knowledge Space Graph", ETRD Springer, 2026
10. "The Path to Conversational AI Tutors", arXiv:2602.19303, 2025
11. Stanford SCALE, "The Evidence Base on AI in K-12: A 2026 Review", 2026
12. Kestin et al., "AI Tutoring RCT", *Nature Scientific Reports*, 2025
13. Aulagnon, Cristia, Cueto & Malamud, "Streaks RCT Peru (60,000 students)", 2024
14. Dianita et al., "Micro-breaks experiment", Kyoto University, 2024
15. Biwer et al., "Pomodoro vs self-regulated breaks", *British Journal of Educational Psychology*, 2023
16. Lodge & Loble, "Metacognitive laziness in AI tutoring", University of Technology Sydney, 2026
17. Kosmyna et al., "Your Brain on ChatGPT", arXiv:2506.08872, 2025
18. Gerlich, "AI Tools and Critical Thinking", *MDPI Societies*, 2025
19. Weissburg et al., "LLMs are Biased Teachers", arXiv:2410.14012, 2024
20. Fleig, "Towards Multimodal Affective Intelligence in Educational AI", UCSD, 2025
21. Bijl, "Skill Trees: A Framework for Structuring Education", *Koli Calling*, 2025
22. An et al., "Rate-Distortion Guided KG Construction", 2025
23. FSRS v6, Open Spaced Repetition, 2025-2026
24. Cepeda et al., "Distributed Practice in Verbal Recall Tasks", *Psychological Bulletin*, 2006
25. Kang, "Spaced Repetition Promotes Efficient and Effective Learning", *Policy Insights from Behavioral and Brain Sciences*, 2016
26. Dunlosky et al., "Improving Students' Learning With Effective Learning Techniques", *Psychological Science in the Public Interest*, 2013
27. Microsoft Azure, "Multi-Agent Best Practices", 2025
28. Anthropic, "Building Effective Agents", 2025

---

*Documento preparado el 11 de junio de 2026. Las referencias reflejan el estado del arte a esta fecha. LearnIt se diseña para una implementación en 20 semanas con iteración continua posterior. La versión 2.0 incorpora todas las decisiones de diseño tomadas en conversación con el autor del proyecto.*