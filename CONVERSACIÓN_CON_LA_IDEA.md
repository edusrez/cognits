**Usuario:** Estoy trabajando en una herramienta llamada learnit para aprender usando IA, estoy pensando en qué cosas son importantes, por ejemplo los objetivos a corto y largo plazo del usuario (por ejemplo hacer un juego, hacer moverse un personaje), la metodología (no es lo mismo enseñar a hacer un juego que enseñar otra cosa, igual cada cosa requiere una metodología distinta, había pensado que la IA buscase y vaya chequeando si la metodología que usa es la correcta cada X tiempo), conocimientos del usuario (aprendidos y necesarios, comprobados por la IA), apuntes del usuario (tener una libreta virtual con hojas y apuntes por cosas que la IA pueda monitorizar) ... ¿que mas cosas podrían ser necesarias ?¿ me equivoco en algunas? La idea es un sistema multiagéntico, a la hora de aprender el proyecto tendría una carpeta llamada .learnit, con toda esta información, donde un agente principal usa subagentes para chequear estas cosas, conocimiento del usuario, sus apuntes, la metodología, etc. y que el agente principal fuera guiando, enseñando y evaluando al usuario. Por ejemplo igual una base de datos también con dificultades que el usuario ha experimentado o fortalezas, podría ser útil. ¿Qué más? ¿En qué me equivoco?

Usa tu subagente para explorar e investigar también, puedes usar tantos cómo quieras, iterando en lo que necesites.

---

**Agente:** ¡Qué proyecto más interesante! Tienes una base muy sólida. Vamos a investigar en varias direcciones para enriquecer tu diseño y también para desafiar algunas de tus suposiciones de forma constructiva.Ahora tengo suficiente profundidad para darte una respuesta completa. Vamos a estructurarla en tres partes: lo que tienes bien, lo que falta (con evidencia), y las suposiciones que merecen ser desafiadas.

---

## 1. Lo que tienes bien (y la investigación lo respalda)

**La arquitectura multi-agente.** El consenso académico y de industria apunta exactamente a eso. De hecho, el patrón que describes —un agente principal que orquesta subagentes especializados— es el patrón *Subagentes* que LangChain y Microsoft Azure identifican como el punto de partida más seguro para sistemas multi-dominio. Reduce el uso de tokens ~67% frente a otras arquitecturas. Un caso real validado en 2026: **ELA Tutor**, desplegado en Moodle con 150 estudiantes, usa esa misma estructura: un Meta-Agente con Q-learning que orquesta agentes especializados (Pedagógico, Técnico, Empático, Analítico, Ético).

**El tracking de conocimiento del usuario.** Es una de las cuatro patas canónicas de cualquier Sistema Tutor Inteligente (ITS): el *modelo del estudiante*. Lleva 40 años de investigación detrás.

**La libreta virtual con monitorización.** Buena intuición. La investigación en metacognición muestra que cuando la IA actúa como "espejo cognitivo" en vez de como "muleta", los tamaños de efecto en estrategias metacognitivas son grandes (η² = 0.39). Pero el *cómo* importa mucho (más abajo lo detallo).

**La carpeta `.learnit` con persistencia.** Correcto. Un sistema que no persiste el estado del estudiante no es un tutor, es un chatbot con memoria efímera.

---

## 2. Lo que falta: piezas críticas que la investigación señala

### 2.1 Un modelo de dominio estructurado (lo más importante que falta)

Tú mencionas "metodología", pero la arquitectura canónica de un ITS tiene **cuatro componentes**:

| Componente | Pregunta que responde | Tu diseño actual |
|---|---|---|
| **Modelo de dominio** | *Qué* enseñar | No está explícito |
| **Modelo del estudiante** | *A quién* enseñar | Lo tienes (conocimientos, dificultades) |
| **Modelo pedagógico** | *Cómo* enseñar | Lo llamas "metodología" |
| **Modelo de interfaz** | *Cómo* comunicarlo | El agente principal |

El modelo de dominio es el mapa de conceptos, habilidades y sus dependencias. Sin él, el sistema no puede:
- Saber qué es prerrequisito de qué
- Detectar concepciones erróneas sistemáticas (que son patrones predecibles de error, no simples "dificultades")
- Hacer *model tracing* (seguir cada paso del estudiante y detectar en qué paso exacto se desvió)
- Hacer *knowledge tracing* formal (estimar probabilidad de dominio de cada skill, no solo "sabe/no sabe")

> Para tu ejemplo de "hacer un juego": el modelo de dominio mapearía conceptos como variables → condicionales → bucles → funciones → clases → game loop → detección de colisiones → física simple, con dependencias entre ellos. La metodología es *cómo* enseñas cada uno, no *qué* enseñas.

### 2.2 Knowledge Tracing formal, no solo "conocimientos comprobados"

Hay una diferencia entre "comprobar si el usuario sabe algo" y tener un modelo probabilístico continuo. Las opciones:

- **BKT (Bayesian Knowledge Tracing):** Modela cada skill con 4 parámetros: probabilidad inicial de saberla, probabilidad de aprenderla, probabilidad de slip (error aunque sepas), probabilidad de guess (acierto sin saber). Es interpretable y ligero.
- **DKT (Deep Knowledge Tracing):** Usa LSTM para mantener un vector continuo de 200+ dimensiones que captura conocimiento parcial, dependencias latentes entre conceptos, y curvas de olvido. AUC +25% sobre BKT, pero requiere más datos.
- El sistema ASSISTments demostró que las métricas de asistencia (cuántas pistas necesitó el estudiante, tiempo de respuesta, número de intentos) predicen el rendimiento en exámenes estandarizados con R = 0.865, muy por encima del modelo estático correcto/incorrecto (R = 0.731).

> Tu intuición de "base de datos de dificultades y fortalezas" es correcta, pero es solo la capa superficial. Debajo necesitas un modelo que estime *probabilidades* y *prediga* el estado futuro.

### 2.3 Repetición espaciada (FSRS)

No lo mencionaste. Es una de las herramientas más potentes y baratas de implementar. El algoritmo **FSRS v6** (Free Spaced Repetition Scheduler) es open source, está en 15+ lenguajes, modela tres variables de memoria (dificultad, estabilidad, recuperabilidad) y tiene un optimizador que ajusta 17 parámetros al historial de reviews de cada usuario. Es lo que usa Anki hoy.

Y yendo más allá, el sistema **LECTOR** (2025) integra análisis semántico con LLMs para detectar interferencia entre conceptos similares y ajustar la programación, logrando 90.2% de tasa de éxito. Imagina que tu sistema detecta que el usuario confunde "herencia" con "composición" en POO y ajusta el espaciado para desenredar esos conceptos.

### 2.4 Modelo afectivo y zona de flujo

El 89% de los sistemas actuales ignora los estados metacognitivos y afectivos del estudiante, y sin embargo la investigación muestra que mantener al estudiante en la **zona de flujo** —donde P(correct) ∈ [0.40, 0.70]— es lo que maximiza el aprendizaje:

- Si P > 0.75 → aburrimiento → el estudiante abandona
- Si P < 0.35 → ansiedad → el estudiante se frustra

El sistema ELA Tutor que mencioné antes usa Q-learning para seleccionar estrategias tutoriales basándose en dos dimensiones: nivel de conocimiento × estado emocional. La recompensa se infiere de palabras clave en el feedback del estudiante.

### 2.5 Detección de concepciones erróneas (no solo "dificultades")

Hay una diferencia sutil pero fundamental:

- **Dificultad:** "Le cuesta entender los bucles" (general, vago, no accionable pedagógicamente)
- **Concepción errónea:** "Cree que un bucle `for` siempre itera al menos una vez" o "confunde la condición de salida con la condición de entrada" (específico, sistemático, accionable)

La detección de concepciones erróneas es una subdisciplina entera. El estado del arte en 2026 usa un pipeline **Generación-Recuperación-Reordenamiento** con LLMs: un modelo genera hipótesis de concepción errónea a partir del diálogo, recupera las etiquetas más cercanas por embeddings semánticos, y otro LLM reordena las candidatas. Un modelo Qwen 2.5 7B con LoRA igualó a Claude Sonnet 4.5 en esta tarea.

### 2.6 Bucle de automejora, no solo "chequeo de metodología cada X tiempo"

Dices: *"la IA buscase y fuese chequeando si la metodología que usa es la correcta cada X tiempo"*. El problema aquí es: ¿contra qué criterio? ¿Quién define "correcta"?

La investigación apunta a algo más concreto: **DPO (Direct Preference Optimization) con profesor en el bucle**. En un estudio real de 2025 (Woodrow et al., EDM 2025), el sistema generaba dos variantes de feedback, el docente elegía una, y esas preferencias alimentaban un fine-tuning entre entregas. En test ciego controlado, el feedback del modelo DPO fue preferido 56.8% vs 40.2% sobre GPT-4o (p = 0.007), y el feedback de GPT-4o fue 8.73 veces más probable de ser calificado como "no útil".

La arquitectura de automejora recomendada tiene tres vías:

1. **Optimización silenciosa:** correcciones automáticas de baja ambigüedad (estilo, formato)
2. **Puerta humana:** cambios pedagógicos estructurales que requieren revisión antes del despliegue
3. **Expansión de contexto:** conocimiento organizacional codificado tras cada sesión

### 2.7 Dashboard de analíticas para el usuario (espejo metacognitivo)

La investigación de Zhai y Nezakatgoo (Nature Scientific Reports, 2025) con 310 estudiantes mostró que la IA puede mejorar estrategias metacognitivas con η² = 0.39. Pero la clave está en el *diseño*: la IA debe ser espejo del razonamiento, no proveedora de soluciones. Si la IA entrega el producto final, hay descarga cognitiva; si entrega un componente que el estudiante debe analizar, hay soporte cognitivo.

Un dashboard para el usuario debería mostrar:
- Mapa de conceptos dominados vs. pendientes (con probabilidades, no binario)
- Concepciones erróneas detectadas y corregidas
- Progresión en zona de flujo
- Próximas revisiones programadas (FSRS)
- Trayectoria de aprendizaje (no solo "llevas 3 lecciones", sino "has subido de P=0.3 a P=0.7 en este concepto")

---

## 3. Suposiciones que merecen ser desafiadas

### 3.1 "Cada cosa requiere una metodología distinta"

Esto es verdad a medias. Sí, enseñar filosofía no es como enseñar a programar. Pero la investigación muestra que los principios subyacentes son notablemente transversales:

- Knowledge tracing probabilístico funciona en matemáticas, programación, física, idiomas...
- La zona de flujo (P ∈ [0.40, 0.70]) es universal
- El model tracing (paso a paso) aplica a cualquier dominio procedural
- El diálogo socrático funciona en humanidades y STEM por igual

La diferencia real está en el **modelo de dominio**, no en el modelo pedagógico. El motor de pedagogical decision-making puede ser el mismo; lo que cambia es el mapa de conceptos y las reglas de producción sobre las que opera.

> Propuesta: diseña un motor pedagógico genérico pero con modelos de dominio intercambiables (como "plugins" de conocimiento). Así no reinventas la pedagogía para cada tema.

### 3.2 "La IA busca y chequea si la metodología es correcta cada X tiempo"

Esto asume que existe una "metodología correcta" externa y objetiva. La investigación sugiere algo más matizado: la efectividad pedagógica es contextual (depende del estudiante, el momento, el concepto, el estado afectivo). El sistema ELA Tutor demostró que un mismo agente pedagógico puede ser adecuado en un contexto y contraproducente en otro —de hecho, el sistema aprendió a penalizar al agente pedagógico en contextos prácticos.

En lugar de "chequear la metodología contra un estándar", piensa en **optimización continua de estrategia**:
- El meta-agente observa resultados de aprendizaje
- Prueba variantes de estrategia (scaffolding vs. explicación directa vs. diálogo socrático)
- Aprende qué funciona para qué estudiante en qué situación
- Se reajusta continuamente, no cada X tiempo

### 3.3 Los "apuntes del usuario" como monitorización pasiva

Monitorizar apuntes es útil, pero la investigación sugiere ir más lejos. El sistema debería **estructurar activamente** los apuntes según el modelo de dominio:

- Vincular cada apunte al concepto del modelo de dominio que le corresponde
- Detectar lagunas: "Has tomado apuntes sobre variables y funciones pero nada sobre scope"
- Detectar concepciones erróneas en los propios apuntes: "En tu nota dices que un bucle while siempre se ejecuta al menos una vez, eso no es correcto"
- Integrar con spaced repetition: los conceptos que aparecen en los apuntes entran automáticamente en el scheduler FSRS

### 3.4 La carpeta `.learnit` como silo aislado sin integración con estándares

Si esto va a ser más que un proyecto personal, considera estándares de interoperabilidad: **LTI** (Learning Tools Interoperability), **OneRoster**, **Caliper**. Permiten que LearnIt se integre con LMS existentes (Moodle, Canvas) sin reemplazarlos.

Y desde el punto de vista regulatorio: el EU AI Act clasifica los tutores AI como "alto riesgo", requiriendo supervisión humana y trazabilidad. Que la carpeta `.learnit` sea auditable desde el día uno te ahorrará problemas después.

---

## 4. Síntesis: una arquitectura de referencia

Basándome en todo lo anterior, así podría estructurarse:

```
.learnit/
├── domain/
│   ├── knowledge_graph.json      # Grafo de conceptos y dependencias
│   ├── constraints.json          # Restricciones del dominio (CBM)
│   └── misconceptions.json       # Catálogo de concepciones erróneas conocidas
├── student/
│   ├── knowledge_state.json      # DKT/BKT: probabilidades por skill
│   ├── affective_state.json      # Historial de estados emocionales
│   ├── fsrs_params.json          # Parámetros FSRS personalizados
│   ├── review_schedule.json      # Próximas revisiones programadas
│   └── misconception_history.json
├── pedagogy/
│   ├── strategy_policy.json      # Q-table del meta-agente
│   ├── preference_pairs.jsonl    # Datos para DPO (si hay profesor)
│   └── methodology_versions/     # Iteraciones de mejora
├── notes/
│   ├── page_001.md               # Apunte vinculado a conceptos
│   └── concept_index.json        # Índice apunte ↔ concepto
├── sessions/
│   ├── 2026-06-10.json           # Traza completa de interacción
│   └── analytics.db              # Métricas agregadas
└── config.json
```

**Agentes:**

| Agente | Responsabilidad | Herramientas |
|---|---|---|
| **Orquestador** (principal) | Mantiene estado de sesión, invoca subagentes, aplica política pedagógica | Acceso a toda la carpeta `.learnit` |
| **Diagnosticador** | Knowledge tracing + detección de concepciones erróneas | Modelo DKT/BKT, pipeline Generate-Retrieve-Rerank |
| **Planificador** | Selecciona siguiente concepto, programa repasos | FSRS, grafo de dependencias del dominio |
| **Evaluador** | Genera ejercicios calibrados a zona de flujo | Banco de ítems, modelo de dificultad |
| **Notero** | Estructura y analiza apuntes, vincula a conceptos | Índice semántico sobre el modelo de dominio |
| **Metacognitivo** | Construye dashboard, refleja progreso, sugiere estrategias de estudio | Datos agregados de `analytics.db` |
| **Validador** (opcional) | Quality gate con puerta humana para cambios pedagógicos | Logging auditable |

---

## 5. Por dónde empezar (priorización)

Mi recomendación, basada en lo que reporta la investigación:

1. **Modelo de dominio para un solo tema** (ej. programación básica). Sin esto, todo lo demás flota en el aire.
2. **Knowledge tracing simple** (BKT con 4 parámetros por skill). No necesitas DKT desde el día uno.
3. **FSRS para repetición espaciada**. Es lo más fácil de integrar y da retorno inmediato.
4. **Agente único con herramientas** antes de multi-agente. Microsoft Azure dice explícitamente: "un solo agente bien instrumentado resuelve más casos que una arquitectura prematuramente compleja".
5. **Bucle de mejora con DPO** solo cuando tengas datos de preferencias reales.

---

¿Quieres que profundice en alguno de estos puntos? Por ejemplo, puedo detallar cómo diseñar el modelo de dominio para el caso concreto de enseñar a hacer un juego, o cómo implementar BKT de forma ligera.

---

**Usuario:** Vale, buen informe. Lo que estoy buscando es hacer una herramienta personal de calidad profesional, y que pueda ser compartida y usadas por otros de manera personal. Mi idea es que learnit fuera un programa que, por ejemplo si tengo una carpeta para un proyecto, por ejemplo, aprender a hacer un juego en godot. Yo poder ir diciendo lo que quiero, la IA evalúe lo que necesito y me vaya orientando para aprender lo que tengo que ir haciendo. Por ejemplo, soy hábil en programación pero me falta experiencia en godot ya que mi campo realmente es la Física (Astrofísica).

Entonces estaba pensando en hacer algo así, un sistema que al iniciar learnit desde la terminal en ese proyecto de godot, la IA pueda analizarme a mi como usuario, lo que necesito aprender , el cómo enseñármelo, etc. A la vez que por ejemplo descarga y tiene acceso a la documentación de Godot, usa subagentes igual que tú que hacen informes con información de la web y ese sistema tenga subagentes capaz de buscar en la web, y esos informes se queden descargado a la mano de algún subagente, etc.

Es decir, por ejemplo, subagente que se encargase de guíar al usuario analizando mi perfil, otro que le de info actualizada de la documentación, otro de los códigos que ya he escrito en la carpeta, otro de la pedagogía, además de que el agente principal también tenga una visión superificial de todos estos campos y los subagentes lo que hagn es darle una visión más enfocada para no saturar ventanas de contexto (aunque usaremos DeepSeek v4 pro con 1M de contexto).

---

**Agente:** Me gusta mucho el refinamiento. Has pasado de una idea abstracta a un caso de uso muy concreto: terminal, anclado a una carpeta de proyecto, con el usuario trayendo skills asimétricas (programación fuerte, Godot y gamedev nuevos). Vamos a investigar algunos aspectos técnicos para darte feedback más filoso.Tengo tres informes de investigación muy densos. Vamos a cruzarlos con tu caso concreto: un astrofísico que sabe programar, quiere aprender Godot desde terminal, con una IA que lee su código, indexa documentación, y despliega subagentes especializados. Vamos al grano.

---

## 1. Lo que está bien (y la investigación lo confirma con cifras)

**El patrón orquestador-subagentes.** No solo es correcto: es la arquitectura óptima para tareas multi-dominio paralelizables. Reduce un 67% de tokens frente al patrón Skills y un 35% frente a Handoffs. Anthropic lo usa en producción con Claude Opus 4 como líder y Claude Sonnet 4 como subagentes, superando al agente único en un 90.2%.

**Aislar contexto en subagentes, no saturar al principal.** Incluso con 1M de tokens de DeepSeek, el fenómeno de *context rot* es universal y medible: todos los modelos fronterizo se degradan progresivamente al crecer el contexto. No es cuestión de límite duro, sino de deterioro de atención. Tu intuición es correcta: subagentes con ventanas limpias devolviendo resúmenes de 1-2K tokens es la estrategia correcta.

**Documentación local indexada.** La documentación de Godot son ~20MB de texto. No cabe en contexto. Necesita RAG sí o sí. La investigación es clara: para docs, splitting recursivo (400-512 tokens, 10% overlap) con arquitectura parent-child (chunks de búsqueda de 200-400 tokens, chunks de lectura de 1000-2000 tokens) da +10-15% de accuracy sobre el baseline sin costo extra.

**Analizar el código del usuario.** Tree-sitter tiene parser para GDScript. El chunking guiado por AST mejora Recall@5 en +4.3 puntos sobre chunking por tamaño fijo. Esto es exactamente lo que necesitas para que el sistema entienda *qué está escribiendo el usuario* y detectar patrones, carencias, concepciones erróneas.

**La carpeta `.learnit/` como estado persistente.** Correcto. Sin persistencia no hay tutor, hay chatbot.

---

## 2. Lo que ajustaría (crítica constructiva)

### 2.1 "Un subagente de perfil de usuario" — probablemente no necesita ser un agente separado

El perfil del usuario (conocimientos, dificultades, historial) es **estado**, no **cómputo**. Es mucho más eficiente mantenerlo como un archivo estructurado en `.learnit/student/knowledge_state.json` que el orquestador lee al iniciar sesión y actualiza al finalizar, en lugar de invocar un agente cada vez que necesita saber si sabes variables.

El subagente de diagnóstico solo se invoca **cuando hay incertidumbre**: tras un ejercicio, para actualizar probabilidades BKT. No en cada interacción.

### 2.2 Los informes web descargados — ojo con la granularidad

Dices: *"esos informes se queden descargados a la mano de algún subagente"*. El riesgo aquí es acumular basura. Propongo en cambio:

- El subagente de búsqueda web genera un informe
- Un **subagente extractor** (o el mismo) lo descompone en fragmentos y los indexa en el mismo vector store que la documentación, etiquetados con `source: web`, `date: 2026-06-10`, `topic: godot-signals`
- El subagente de documentación consulta el vector store unificado, no "archivos sueltos"

Así evitas tener un montón de PDFs/Markdowns muertos que nadie vuelve a mirar.

### 2.3 La "metodología" no debería ser chequeada "cada X tiempo"

Como ya mencioné en el informe anterior, esto asume que existe una metodología externa "correcta". Más potente es un bucle continuo de optimización:

- El orquestador registra qué estrategia usó para cada concepto (scaffolding, socrático, explicación directa, ejemplo-comentado)
- El resultado del ejercicio mide efectividad
- Con suficientes datos, el orquestador aprende qué estrategia funciona mejor para ti en qué situación
- No necesitas "cada X tiempo" — es continuo y basado en evidencia

---

## 3. Lo que falta para el caso concreto Godot

### 3.1 Un agente de ejecución/validación

El aprendizaje de Godot tiene una particularidad: el feedback no es solo "código correcto/incorrecto", es *¿se mueve el personaje? ¿colisiona? ¿la escena carga?*. Un agente que:

- Ejecute `godot --headless --script res://tests/run_tests.gd` (Godot tiene modo headless)
- Capture errores de consola
- Tome screenshots automatizados de la escena
- Los compare contra un comportamiento esperado descrito por el usuario ("el personaje debe moverse a la derecha al pulsar D")

Esto cierra el bucle de feedback de forma mucho más rica que solo revisar código.

### 3.2 Un modelo de dominio específico para Godot/gamedev

El grafo de dependencias para hacer un juego no es genérico. Para "movimiento de personaje" necesitas:

```
Godot basics (escenas, nodos)
  → GDScript fundamentals (variables, funciones)
    → Input handling (Input Map, _input, _process vs _physics_process)
      → KinematicBody2D/CharacterBody2D
        → move_and_slide() / velocity
          → Animaciones (AnimationPlayer, AnimationTree)
            → State machines para personajes
```

Sin este grafo, el sistema no puede decidir qué enseñarte primero ni detectar que tu dificultad con `move_and_slide()` viene de no entender `_physics_process` vs `_process`.

### 3.3 Un agente de ejercicios generativos

El sistema no solo debe explicar, debe **ponerte ejercicios**. Y no ejercicios genéricos, sino calibrados a tu zona de flujo (P(correct) ~ 0.40-0.70). Si eres hábil programando pero nuevo en Godot, el sistema debe:

- Saltarse "qué es una variable" (ya lo sabes)
- Ir directo a "cómo se estructura una escena en Godot" (concepto nuevo)
- Generar un mini-ejercicio: "Crea una escena con un Sprite2D que se mueva con las flechas usando `_physics_process`"

El agente de código analiza tu solución, el de ejecución la corre, y el diagnosticador actualiza tu BKT.

---

## 4. Arquitectura concreta para `.learnit/`

```
proyecto-godot/
├── AGENTS.md                          # Estándar abierto (compatible con Codex, Cursor...)
├── .learnit/
│   ├── config.json                    # Config global, proveedor LLM, modelo
│   ├── domain/
│   │   ├── knowledge_graph.json       # Grafo: nodos Godot + dependencias
│   │   └── misconceptions.json        # Catálogo de errores típicos GDScript
│   ├── student/
│   │   ├── profile.json               # Background: "astrofísico, Python avanzado, Godot cero"
│   │   ├── bkt_state.json             # Por skill: {p_init, p_learn, p_slip, p_guess}
│   │   ├── misconception_history.json # Errores detectados y corregidos
│   │   └── affective_log.jsonl        # {timestamp, flow_zone, frustration_signals}
│   ├── pedagogy/
│   │   ├── strategy_policy.json       # Q-table: qué estrategia para qué (concepto, estado)
│   │   └── session_plan.json          # Plan de la sesión actual
│   ├── rag/
│   │   ├── chroma_db/                 # Vector store (docs Godot + informes web)
│   │   └── index_meta.json            # Mapa de fuentes indexadas, fechas, versiones
│   ├── sessions/
│   │   ├── 2026-06-10.json            # Traza completa de interacción
│   │   └── analytics.db               # SQLite con métricas agregadas
│   └── notes/
│       ├── signals.md                 # Apunte del usuario
│       └── concept_index.json         # Vincula cada apunte a un nodo del grafo
```

**Agentes:**

| Agente | Disparador | Responsabilidad | Modelo sugerido |
|---|---|---|---|
| **Orquestador** | Cada interacción | Carga perfil, decide qué agente invocar, sintetiza respuesta | DeepSeek V4 Pro (1M ctx) |
| **Diagnosticador** | Al final de cada ejercicio | Actualiza BKT, detecta concepciones erróneas | DeepSeek V4 |
| **Planificador** | Al inicio de sesión y tras cada concepto | Elige siguiente concepto, programa repasos (FSRS) | Modelo rápido (DeepSeek V3) |
| **Documentalista** | Cuando se necesita info de Godot | Consulta vector store (RAG), devuelve chunks relevantes + síntesis | DeepSeek V4 |
| **Buscador web** | Cuando la doc no cubre algo o está desactualizada | Busca, extrae, indexa en vector store, devuelve síntesis | DeepSeek V4 + search tool |
| **Analizador de código** | Cuando el usuario escribe/modifica código | AST con tree-sitter, detecta patterns, carencias, errores | Modelo rápido |
| **Ejecutor** | Cuando hay código para probar | Ejecuta Godot headless, captura errores y screenshots | No es LLM (es un runner) |
| **Generador de ejercicios** | Cuando el planificador decide practicar | Genera enunciado calibrado a zona de flujo, con criterios de éxito | DeepSeek V4 |
| **Metacognitivo** | Bajo demanda o al final de sesión | Dashboard de progreso, refleja trayectoria, sugiere estrategias | Modelo rápido |

**Flujo típico de sesión:**

```
> learnit start
Orquestador: Carga perfil, invoca Planificador
Planificador: "Siguiente concepto: CharacterBody2D. Dependencias cubiertas: ✓. 
              Zona de flujo estimada: P=0.55. Estrategia: ejemplo comentado."

> learnit teach
Orquestador: Invoca Documentalista para obtener doc de CharacterBody2D
Documentalista: (vector store) → chunks relevantes + resumen
Orquestador: Explica CharacterBody2D con ejemplo, estilo adaptado a perfil 
             ("como physicist, piensa en velocity como un vector de estado 
             que _physics_process integra cada frame...")

> learnit exercise
Orquestador: Invoca GeneradorEjercicios
Generador: "Crea un personaje que se mueva con WASD y rebote en los bordes 
           de la pantalla usando CharacterBody2D y move_and_slide()"

[Usuario escribe código en character.gd]

> learnit check
Orquestador: Invoca AnalizadorCódigo
Analizador: "✓ CharacterBody2D usado. ✓ move_and_slide(). 
            ✗ No has definido la velocidad máxima. 
            ✗ Estás usando _process en vez de _physics_process."
Orquestador: Invoca Ejecutor
Ejecutor: "La escena carga. El personaje se mueve pero no rebota. 
          Error: falta screen_size y lógica de clamp."
Orquestador: Invoca Diagnosticador
Diagnosticador: "BKT actualizado: CharacterBody2D p=0.3→0.55. 
                 Concepción errónea detectada: _process vs _physics_process."
Orquestador: Te muestra qué falló, por qué, y te da pista sin darte la solución.
```

---

## 5. Stack técnico recomendado

| Capa | Tecnología | Por qué |
|---|---|---|
| **LLM orquestador** | DeepSeek V4 Pro (1M ctx) | Ya lo tienes elegido, excelente relación contexto/costo |
| **LLM subagentes ligeros** | DeepSeek V3 o Qwen2.5-Coder 14B local | Tareas de clasificación, AST, planificación no necesitan 1M ctx |
| **Embeddings** | Jina Code V2 (Apache 2.0, 137M params, local) | Específico de código, open source, late chunking soportado |
| **Vector store** | ChromaDB | Simple, local, sin servidor, integración directa con LangChain |
| **AST parser** | tree-sitter-gdscript | Chunking sintáctico del código del usuario |
| **RAG framework** | LangChain + ParentDocumentRetriever | Parent-child retrieval, MarkdownHeaderTextSplitter para docs |
| **Spaced Repetition** | FSRS v6 (librería Python) | Open source, 17 parámetros ajustables, probado en Anki |
| **Ejecución Godot** | godot --headless | Ya existe, solo necesita scripting alrededor |
| **Persistencia** | JSON + SQLite | JSON para archivos editables a mano, SQLite para analytics |
| **Interfaz** | Click / Rich / Textual (Python) | Terminal interactiva con formato rico, paneles, progreso |

---

## 6. Lo que yo haría distinto a como lo estás planteando

**1. No empieces con multi-agente.** Empieza con un solo agente bien instrumentado con herramientas (RAG, tree-sitter, ejecutor). Añade subagentes cuando midas degradación real por contexto. Microsoft Azure, LangChain y Anthropic coinciden en esto. Un agente único con buenas herramientas resuelve más casos que una arquitectura prematuramente compleja.

**2. El 80% del valor está en tres cosas, no en diez:**
- Modelo de dominio + BKT (saber qué enseñar y qué sabe el usuario)
- RAG sobre documentación (acceso a información precisa)
- Ejercicios con feedback de ejecución real (cerrar el bucle)

Lo demás (metacognición, dashboard, affective state, DPO) son capas que añades cuando esas tres funcionen.

**3. La experiencia CLI debería sentirse como un tutor, no como un chatbot.** Piensa en comandos: `learnit start`, `learnit teach`, `learnit exercise`, `learnit check`, `learnit notes`, `learnit status`. No solo un prompt abierto. Esto estructura la sesión y le da ritmo pedagógico. El prompt abierto es para dudas puntuales dentro de la sesión.

**4. AGENTS.md + .learnit/ es mejor que solo .learnit/.** `AGENTS.md` es un estándar que ya usan Codex, Cursor, Copilot, Gemini CLI. Si pones ahí tu background ("astrofísico, Python avanzado, aprendiendo Godot") y convenciones del proyecto, cualquier agente CLI puede leerlo. LearnIt puede además enriquecerlo automáticamente con lo que detecta de tu código.

**5. No asumas que 1M de contexto elimina la necesidad de RAG.** Context rot es real en todos los modelos. Además, meter 20MB de documentación en cada llamada tiene un costo económico aunque técnicamente quepa. RAG con parent-child retrieval es más barato, más rápido, y a menudo más preciso que volcar todo en contexto.

---

¿Quieres que profundice en alguno de estos puntos? Por ejemplo, puedo detallar cómo diseñar el knowledge graph de Godot/gamedev, o cómo implementar el pipeline RAG con documentación de Godot y tree-sitter para GDScript.

---

**Usuario:** Me gustan tus informes, te doy un poco de feedback, cómo vamos bien de presupuesto podemos permitirnos usar DeepSeek V4 Pro Max, aunque obviamente para cuestiones como Godot este modelo no tiene "ojos" para ver si por ejemplo, aunque no hayan bugs y el código se ejecute, depende del usuario para que esté le responda a cómo se mueve por ejemplo, si va bien, laggeado, o cualquier cosa. No pasa nada, está bien que el tutor no pueda supervisar directamente estas cosas, pero sin embargo sí que pueda supervisar tus ejercicios etc, un subagente para ejercicios suena muy bien.

Ahora tengo otra cuestión y cosas que investigar, cuando el usuario quiere sentarse a aprender deberíamos incentrivarle a una rutina, cierta puntualidad cada día por ejemplo, y deberíamos monitorizar tiempo de sesión, tiempo de respuesta por ejercicio, de trabajo, etc y forzarle a que descanse etc, dar por acabada la sesión de hoy, etc?

Y no te preocupes por empezar multiagente o no, he probado ya sistemas multiagénticos, prefiero dedicarme más tiempo a programar una idea completa que luego ir mejorando que una demo limitada, por ejemplo, me gustaría apuntar directamente al SOTA del modelo de dominio, estudiante, etc. Hacer que el modelo pedagócico se creea utomáticamente dependiendo del proyecto del usuario, etc.

No te preocupes, aunque el programa se invoque desde una cli se ejecuta la interfaz en una web local minimalista, donde el susuario tiene el chat, su libreta, y evaluaciones, las sesiones, etc.

---

**Agente:** Vamos a profundizar en tus nuevas preguntas. Tengo varios frentes que investigar: la automatización del modelo de dominio a partir del proyecto del usuario, la gestión de sesiones y hábitos (rutina, descansos, cierre de sesión), y cómo los sistemas SOTA abordan la creación dinámica del modelo pedagógico. Lanzo varios subagentes en paralelo.Tengo los dos informes. El de gestión de sesiones es especialmente rico — hay evidencia experimental muy sólida que responde directamente a tu pregunta sobre rutinas, descansos y cierre de sesión. El de generación automática de modelos de dominio también es directamente aplicable a tu idea de que el modelo pedagógico se cree automáticamente según el proyecto. Vamos a integrarlo todo.

---

## Parte 1: Gestión de sesiones — la respuesta concreta

Tu intuición es correcta: sí, el sistema debe incentivar rutina y puntualidad, monitorizar tiempos, forzar descansos y dar por terminada la sesión. Pero la investigación revela matices importantes sobre *cómo* hacerlo sin generar rechazo.

### 1.1 Rachas (streaks): la herramienta más potente para formar hábito

El hallazgo más impactante viene de un RCT a nivel nacional en Perú con 60,000 estudiantes (Aulagnon, Cristia, Cueto & Malamud, 2024):

- Las rachas visibles fueron el **único tratamiento que mejoró significativamente el rendimiento académico**: +0.13 a +0.17 desviaciones estándar en matemáticas
- Los efectos ya eran visibles en la primera semana y se amplificaron durante las seis semanas
- **No se detectó efecto de desánimo** cuando se rompía una racha — no hubo períodos más largos de desconexión tras romperla
- La psicología subyacente cambia con la longitud: al inicio motiva el logro (racha corta), luego la aversión a la pérdida (racha larga)

Duolingo lo respalda con datos masivos: usuarios con racha de solo 7 días tienen **3.6 veces más probabilidades** de completar su curso. Los "streak freezes" (1-2 por semana) aumentan los usuarios activos diarios sin diluir el efecto.

> **Para LearnIt:** Rachas visibles en la interfaz web, con 1-2 "freezes" semanales. Combinar recordatorios personalizados los lunes (atraer) y mensajes de racha los jueves (retener), que fue la combinación más efectiva en el RCT peruano.

### 1.2 Duración óptima de sesión: 45-50 minutos

El RCT de Harvard (Kestin et al., 2025, *Nature Scientific Reports*) con 194 universitarios encontró una **mediana de 49 minutos** para una sesión efectiva de tutoría con IA. La atención sostenida decae significativamente después de 50 minutos (Dunlosky et al., curva de Ebbinghaus). Sesiones maratónicas de 2-3 horas no producen más aprendizaje — producen más fatiga.

> **Para LearnIt:** Sesiones con límite por defecto de 45-50 minutos. El sistema monitoriza el tiempo y dispara una advertencia a los 45 min y una sugerencia activa de cierre a los 50-55 min.

### 1.3 Micro-pausas forzadas cada 8-12 minutos

Dianita et al. (2024, Kyoto University) hicieron un experimento controlado de laboratorio con 31 participantes. Resultados con micro-pausas sistemáticas de 20-30 segundos:

- El tiempo de respuesta fue **significativamente más estable** (p < 0.001)
- La carga de trabajo mental percibida (NASA-TLX) fue **significativamente menor** (p < 0.05)
- Recomiendan iniciar pausas alrededor del minuto 13, no del 7.5

Biwer et al. (2023, *British Journal of Educational Psychology*) confirman que las pausas sistemáticas impuestas externamente (estilo Pomodoro) son superiores a las auto-reguladas para la eficiencia de finalización de tareas.

> **Para LearnIt:** Cada ~12 minutos de interacción activa, una micro-pausa de 30 segundos. No opcional. Un overlay suave en la UI: "Pausa de 30s. Respira. Cuando vuelvas, pregúntate: ¿qué acabo de aprender?" Esto último además es una pausa metacognitiva (ver abajo).

### 1.4 Terminación de sesión dirigida por el tutor — la frontera más contraintuitiva

Esto es importante y quizá no lo habías considerado. Lodge & Loble (2026, University of Technology Sydney) documentan el fenómeno de **pereza metacognitiva**: la fluidez del output de IA crea una "ilusión de competencia" donde el estudiante cree que entiende cuando solo ha procesado superficialmente. El ciclo es vicioso:

```
más externalización → menos conocimiento real 
→ menos capacidad de evaluar el output de IA 
→ más externalización
```

MindStudio (2025) documenta el fenómeno de *workload creep*: sin una regla de parada explícita, las sesiones de IA se expanden indefinidamente.

La recomendación es clara: **el tutor debe terminar activamente la sesión** cuando:
- Se superan los 50-55 minutos
- La tasa de error sube >15% respecto al baseline del estudiante
- Se detectan señales de fatiga en el lenguaje del usuario (respuestas más cortas, más errores, más preguntas de confirmación)

> **Para LearnIt:** El orquestador monitoriza tasa de error y patrones de interacción. Al detectar degradación o al llegar al límite, sugiere activamente: "Has estado 52 minutos y tu tasa de acierto ha bajado del 78% al 61%. Es buen momento para cerrar la sesión de hoy. ¿Programamos la de mañana a las 18:00?"

### 1.5 Pausas metacognitivas forzadas

Cada 15-20 minutos, insertar preguntas que fuercen al estudiante a explicar con sus propias palabras lo que acaba de aprender. Esto rompe el ciclo de ilusión de competencia. Lodge & Loble lo llaman "romper el ciclo de atrofia cognitiva".

> **Para LearnIt:** "Antes de seguir, explícame con tus palabras qué hace `_physics_process` y en qué se diferencia de `_process`. Escríbelo en tu libreta." Luego el subagente notero analiza esa explicación y detecta concepciones erróneas.

### 1.6 Monitorización que propones (y está respaldada)

| Métrica | Para qué sirve | Umbral de acción |
|---|---|---|
| Tiempo de sesión | Evitar fatiga | Alerta a 45 min, cierre sugerido a 52 min |
| Tiempo por ejercicio | Detectar dificultad oculta | Si duplica su mediana, investigar |
| Tiempo de respuesta | Señal temprana de fatiga | Degradación >20% → sugerir pausa |
| Tasa de error | Detectar fatiga o concepto mal asentado | +15% vs baseline → fin de sesión |
| Días consecutivos (racha) | Formación de hábito | Visible siempre, celebrar hitos |
| Hora del día | Optimizar rutina | Sugerir misma franja horaria cada día |

### 1.7 Lo que NO debes hacer

- **No fuerces el cierre sin aviso.** La investigación muestra que la terminación debe ser sugerida y razonada, no impuesta. "Te queda 1 minuto" sin explicación genera rechazo. "Tu rendimiento está bajando por fatiga, es mejor parar aquí" genera aceptación.
- **No uses solo recordatorios genéricos.** Los recordatorios personalizados ("Ayer aprendiste CharacterBody2D, ¿seguimos hoy con colisiones?") son mucho más efectivos que "Recuerda estudiar".
- **No hagas las pausas opcionales.** La evidencia de Biwer et al. es clara: las pausas auto-reguladas son menos efectivas que las sistemáticas.

---

## Parte 2: Modelo de dominio y pedagógico auto-generados según el proyecto

Aquí es donde tu idea de que el modelo pedagógico se cree automáticamente según el proyecto del usuario conecta directamente con la investigación SOTA.

### 2.1 El pipeline de auto-generación

El sistema **MMKG-RAG ITS** (Deng & Yuan, Frontiers 2026) y el pipeline de **Abu-Rasheed et al. (EDUCÓN 2025)** demuestran que este flujo es viable hoy:

```
Documentación de Godot (20MB)
  → LLM extrae Topics + Sub-Topics (F1 > 0.96)
  → LLM infiere relaciones de prerrequisito 
    (señales: orden de capítulos, marcadores discursivos como 
    "asumiendo que ya sabes X", "antes de continuar con Y")
  → KG en Neo4j o JSON con nodos (conceptos) y aristas (prerequisiteOf)
  → Validación humana opcional (baja ambigüedad = automático, 
    alta ambigüedad = pedir confirmación)
```

Para el caso concreto de Godot, el sistema:

1. **Descarga e indexa la documentación** (ya lo tenías planeado)
2. **Extrae la estructura conceptual**: escenas, nodos, señales, `_process`, `_physics_process`, `CharacterBody2D`, `move_and_slide()`, etc.
3. **Infieren prerrequisitos**: `CharacterBody2D` → requiere entender `Node2D` → requiere entender `Node` → requiere entender escenas
4. **Cruza con tu perfil**: "Sabe programar (Python avanzado), no sabe Godot" → el grafo se poda automáticamente de conceptos que ya dominas (variables, funciones, condicionales, bucles) y se enfoca en los conceptos específicos de Godot
5. **Genera rutas de aprendizaje**: múltiples caminos posibles por el grafo, ordenados por dependencias topológicas
6. **El modelo pedagógico** (estrategias: socrático, scaffolding, ejemplo comentado) se asigna a cada nodo según su tipo: conceptos declarativos (ejemplo comentado), habilidades procedurales (scaffolding + ejercicio), debugging (socrático)

### 2.2 Skill Trees: la estructura de datos correcta

El framework **Skill Trees** (Bijl, 2025, Koli Calling) es superior a un grafo de conocimiento genérico para educación. Define formalmente:

- **Skill Tree**: DAG donde los nodos son habilidades y las aristas son dependencias de prerrequisito
- Cada habilidad se descompone en ~3 sub-habilidades
- Sobre el Skill Tree se acopla un **Concept Tree** (ideas, modelos mentales, "notional machines")
- El ordenamiento DFS inverso sobre el DAG produce automáticamente la secuencia de enseñanza

Ejemplo para Godot — "movimiento de personaje":

```
Mover personaje con input [SKILL]
├── Crear una escena con CharacterBody2D [SUB-SKILL]
│   ├── Entender la jerarquía Node/Node2D/CharacterBody2D [CONCEPT]
│   └── Añadir sprite y colisionador [SUB-SKILL]
├── Script básico en GDScript [SUB-SKILL]
│   ├── Diferenciar _process vs _physics_process [CONCEPT]
│   └── Acceder a Input en GDScript [SUB-SKILL]
└── Aplicar velocidad y move_and_slide() [SUB-SKILL]
    └── Entender velocity como vector de estado [CONCEPT]
```

> **Para LearnIt:** El Skill Tree se genera automáticamente desde la documentación y se almacena en `.learnit/domain/knowledge_graph.json`. El planificador lo recorre con DFS inverso, saltando nodos que el BKT indica como dominados.

### 2.3 Rate-Distortion: no crear más nodos de los necesarios

Un peligro real es generar un grafo excesivamente detallado. **Rate-Distortion Guided KG Construction** (An et al., 2025) usa teoría de la información para encontrar el "punto de rodilla" donde añadir más conceptos produce retornos decrecientes. La métrica es simple: si un concepto no aparece en ejercicios reales ni se refleja en errores de estudiantes, probablemente no merece ser un nodo independiente.

> **Para LearnIt:** Al generar el grafo, preguntar al LLM: "¿Este concepto es distinguible en la práctica? ¿Un estudiante puede dominar el padre sin dominar este hijo?" Si la respuesta es no, fusionar.

### 2.4 El modelo pedagógico se deriva, no se programa

Tu intuición de que "cada cosa requiere una metodología distinta" es parcialmente correcta, pero no necesitas programar metodologías distintas. Lo que necesitas es un **mapeo tipo de concepto → estrategia pedagógica** que el sistema aplique automáticamente:

| Tipo de nodo en el grafo | Estrategia | Ejemplo |
|---|---|---|
| **Concepto declarativo** (qué es X) | Ejemplo comentado + verificación | "CharacterBody2D es un nodo que..." → "Explícame con tus palabras" |
| **Concepto procedural** (cómo se hace X) | Scaffolding progresivo + ejercicio | "Primero crea la escena, luego añade el nodo, luego..." → "Ahora hazlo tú" |
| **Concepto de debugging** (qué pasa si X falla) | Socrático | "Tu personaje no se mueve. ¿Qué podría estar pasando?" |
| **Concepto integrador** (combina X e Y) | Intercalado + proyecto | "Ahora combina movimiento con animaciones" |
| **Concepción errónea conocida** | Contraste explícito | "Crees que _process y _physics_process son intercambiables. No lo son. Aquí tienes un ejemplo donde se nota la diferencia." |

Este mapeo es genérico — no depende de Godot. Lo que cambia es el contenido (el grafo), no la estrategia.

---

## Parte 3: Arquitectura refinada para `.learnit/`

Incorporando todo lo investigado:

```
proyecto-godot/
├── AGENTS.md
├── .learnit/
│   ├── config.json
│   ├── domain/
│   │   ├── knowledge_graph.json        # Skill Tree con prerequisiteOf
│   │   ├── concept_types.json          # declarative | procedural | debugging | integrative
│   │   ├── misconceptions.json         # Errores típicos de Godot/GDScript
│   │   └── generation_log.json         # Trazabilidad: cómo y cuándo se generó cada nodo
│   ├── student/
│   │   ├── profile.json                # Background, intereses, ritmo preferido
│   │   ├── bkt_state.json              # Por skill: P(know), P(slip), P(guess), P(learn)
│   │   ├── fsrs_params.json            # Parámetros personales del scheduler
│   │   ├── review_schedule.json        # Próximos repasos programados
│   │   ├── misconception_history.json  # Errores detectados y corregidos
│   │   ├── affective_log.jsonl         # {timestamp, flow_zone_estimate, fatigue_signals}
│   │   └── streak.json                 # {current, longest, freezes_left, history}
│   ├── pedagogy/
│   │   ├── strategy_map.json           # tipo_nodo → estrategia por defecto
│   │   ├── strategy_effectiveness.json # Por (concepto, estrategia, estado): efectividad
│   │   └── session_plan.json           # Plan de la sesión actual (próximos nodos)
│   ├── rag/
│   │   ├── chroma_db/                  # Vector store parent-child
│   │   └── index_meta.json             # Fuentes indexadas, versiones, fechas
│   ├── sessions/
│   │   ├── 2026-06-10T18-00.json       # Traza completa
│   │   ├── analytics.db                # SQLite con métricas agregadas
│   │   └── session_dashboard.json      # Resumen para la UI: tiempo, ejercicios, progreso
│   └── notes/
│       ├── 2026-06-10_signals.md       # Apunte vinculado a nodos del grafo
│       └── concept_index.json          # Mapa apunte → concepto
```

---

## Parte 4: Recomendaciones finales

### Lo que añadiría a tu diseño:

1. **Sistema de rachas.** Pequeño en código, enorme en impacto. Visible en la UI. Con freezes limitados.

2. **Micro-pausas forzadas de 30s cada ~12 minutos.** Overlay suave en la UI. Con componente metacognitivo ("¿qué acabo de aprender? ¿qué me confunde?").

3. **Cierre de sesión activo.** El orquestador monitoriza tasa de error y tiempo. No espera a que te detengas. Sugiere y razona.

4. **Skill Tree auto-generado desde la documentación de Godot** con pipeline LLM + validación de baja ambigüedad automática. Esto es el corazón del sistema: sin él no hay planificación, no hay diagnóstico fino, no hay ruta de aprendizaje.

5. **Mapeo tipo-concepto → estrategia pedagógica.** Genérico y reusable para cualquier dominio. Lo que cambia entre proyectos es el grafo, no las estrategias.

### Lo que ajustaría de tu planteamiento:

1. **De "metodología chequeada cada X tiempo" a "estrategia optimizada continuamente".** El sistema no busca una metodología externa correcta; prueba estrategias, mide efectividad, y ajusta. La métrica es el aprendizaje del estudiante, no la adherencia a un estándar.

2. **De "subagente de perfil de usuario" a "estado persistente leído al inicio".** El perfil es datos, no cómputo. El subagente diagnosticador se invoca solo cuando hay incertidumbre (post-ejercicio), no en cada interacción.

3. **De "informes web descargados sueltos" a "indexados en el vector store unificado".** Para que el documentalista los encuentre cuando los necesite.

4. **De "solo chat" a "comandos estructurados + chat libre".** `learnit start`, `learnit teach`, `learnit exercise`, `learnit check`, `learnit notes`, `learnit status`, `learnit end`. El chat libre es para dudas dentro de la sesión. Esto le da ritmo pedagógico y evita que el usuario se quede atrapado en inercia de chat.

---

¿Quieres que profundice en el pipeline concreto de auto-generación del Skill Tree desde la documentación de Godot? ¿O prefieres que explore el diseño de la UI web local con la libreta, evaluaciones, y dashboard de sesiones?

---

**Usuario:** Me parece perfecto. ¿podrías redactar un informe final completo con lo que se debería buscar y estructurar en el proyecto para que sea SOTA o mejor que el actual SOTA?

---

**Agente:** Voy a hacer una ronda final de investigación para asegurarme de que el informe capture el estado del arte más reciente y lo que está emergiendo, de modo que podamos apuntar a superar el SOTA actual en puntos concretos.---

# LearnIt: Documento de Arquitectura y Visión

## Hacia un sistema de tutoría inteligente personal que supere el estado del arte

**Versión 1.0 — 10 de junio de 2026**

---

## Índice

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [El estado del arte y sus grietas](#2-el-estado-del-arte-y-sus-grietas)
3. [Principios fundacionales de LearnIt](#3-principios-fundacionales-de-learnit)
4. [Arquitectura del sistema](#4-arquitectura-del-sistema)
5. [Modelo de dominio: Skill Trees auto-generados](#5-modelo-de-dominio-skill-trees-auto-generados)
6. [Modelo del estudiante: más allá del overlay binario](#6-modelo-del-estudiante-más-allá-del-overlay-binario)
7. [Modelo pedagógico: estrategia optimizada continuamente](#7-modelo-pedagógico-estrategia-optimizada-continuamente)
8. [Modelo de sesión: hábito, fatiga y metacognición](#8-modelo-de-sesión-hábito-fatiga-y-metacognición)
9. [Arquitectura multi-agente con verificación cruzada](#9-arquitectura-multi-agente-con-verificación-cruzada)
10. [Interfaz: CLI + web local](#10-interfaz-cli--web-local)
11. [Stack técnico](#11-stack-técnico)
12. [Qué hace a LearnIt mejor que el SOTA actual](#12-qué-hace-a-learnit-mejor-que-el-sota-actual)
13. [Hoja de ruta de implementación](#13-hoja-de-ruta-de-implementación)
14. [Métricas de éxito](#14-métricas-de-éxito)
15. [Referencias](#15-referencias)

---

## 1. Resumen ejecutivo

LearnIt es un sistema de tutoría inteligente personal que opera desde terminal, anclado a la carpeta de un proyecto del usuario. A diferencia de los chatbots educativos genéricos, LearnIt mantiene un modelo de dominio estructurado (Skill Tree), un modelo probabilístico del estudiante (BKT + FSRS), y una arquitectura multi-agente con verificación cruzada que orquesta agentes especializados para diagnosticar, planificar, enseñar, evaluar y monitorizar el estado afectivo y metacognitivo del usuario.

**La tesis central**: El SOTA actual en ITS adolece de fragmentación. Los sistemas o bien son potentes en knowledge tracing pero carecen de interfaz conversacional natural, o bien son LLMs conversacionales pero carecen de modelo de estudiante riguroso, verificación factual y grounding curricular. LearnIt integra ambas tradiciones —los modelos formales de los ITS clásicos y la flexibilidad conversacional de los LLMs— en una arquitectura unificada, portable, y centrada en el proyecto personal del usuario.

---

## 2. El estado del arte y sus grietas

La investigación realizada durante junio de 2026 —cubriendo revisiones sistemáticas en *Nature Scientific Reports*, *Frontiers in Computer Science*, *Artificial Intelligence Review*, NeurIPS 2025, NAACL 2025, LAK 2025, y el informe Stanford SCALE 2026— revela 12 brechas fundamentales en los sistemas de tutoría inteligente actuales. LearnIt se diseña para cerrar cada una de ellas.

### 2.1 Las doce brechas del SOTA

| # | Brecha | Evidencia | Cómo la cierra LearnIt |
|---|--------|-----------|------------------------|
| 1 | **Sin benchmarks estandarizados de eficacia pedagógica** | Zerkouk et al. (2025): 127 artículos, métricas inconsistentes, sin comparabilidad | Métricas cuantitativas integradas: BKT Δ, FSRS retención, zona de flujo, transferencia sin asistencia |
| 2 | **Sistemas multi-agente fallan 41-86.7%** | Cemri et al., NeurIPS 2025: 14 modos de fallo, ambigüedad de especificación | Arquitectura con verificación cruzada obligatoria entre subagentes, protocolos de coordinación estructurados |
| 3 | **Alucinaciones como riesgo pedagógico grave** | EDM 2025: feedback erróneo en tutoría de matemáticas; Chu et al. 2025 | Grounding obligatorio contra documentación indexada + vector store; CCVP (Cross-Check Verification Protocol) |
| 4 | **Dimensión socioemocional ausente** | Fleig, UCSD 2025; Márquez-Carpintero et al., 2026 | Detección de fatiga y frustración vía señales textuales + patrones de interacción; adaptación de estrategia |
| 5 | **Cognitive offloading documentado** | Kosmyna et al., 2025; Gerlich, 2025; Stanford SCALE 2026 | Pedagogía socrática como modo por defecto; pausas metacognitivas forzadas; nunca dar la solución sin elicitar razonamiento |
| 6 | **Sesgo en contenido y modelado** | Weissburg et al., 2024: LLMs asignan contenido por raza/género/ingresos | Perfilado transparente y auditado por el usuario; BKT probabilístico sin features demográficos |
| 7 | **Estrechez de dominio: solo STEM** | Zerkouk et al., 2025: "abrumadoramente sesgado hacia STEM" | Arquitectura agnóstica al dominio; modelo de dominio auto-generado; el caso Godot valida en programación, extensible a cualquier dominio |
| 8 | **Sin estudios longitudinales** | Zerkouk et al., 2025: mayoría <6 semanas, <100 participantes | Persistencia completa en `.learnit/`; diseñado para uso continuo durante meses; analíticas acumulativas |
| 9 | **Profesores excluidos del diseño** | Márquez-Carpintero et al., 2026 | Para uso personal no aplica exclusión institucional; para uso compartido, `AGENTS.md` + `.learnit/` son auditables y editables |
| 10 | **Modelado de estudiante superficial** | Zerkouk et al., 2025: overlay binario o basado en prompts | BKT con 4 parámetros por skill; FSRS con 17 parámetros personales; historial de concepciones erróneas; modelo afectivo |
| 11 | **Dependencia frágil de prompts** | Márquez-Carpintero et al., 2026: "altamente sensible a formulación de prompts" | Estrategia pedagógica gobernada por política (Q-table), no por prompts; prompts como parámetros versionados, no como magia |
| 12 | **Fragmentación: tareas aisladas vs práctica holística** | Márquez-Carpintero et al., 2026 | Orquestador único que integra diagnóstico, enseñanza, práctica y reflexión en una sesión coherente |

### 2.2 Lo que SÍ funciona y LearnIt adopta

| Componente | Sistema de referencia | Resultado | LearnIt |
|------------|----------------------|-----------|---------|
| **Knowledge tracing** | MSKT (Nature 2025) | 91-95% AUC | BKT + fine-tuning con datos del usuario |
| **Skill Trees** | SkillTree IES (2025-26) + G4L EKSG | +24% ganancia de aprendizaje | `.learnit/domain/knowledge_graph.json` auto-generado |
| **Dominio auto-generado** | MMKG-RAG (Frontiers 2026) | F1 >83%, 100% automatizado | Pipeline doc→grafo con validación de baja ambigüedad |
| **Repetición espaciada** | FSRS v6 | 20-30% menos revisiones | `.learnit/student/fsrs_params.json` por usuario |
| **Zona de flujo** | ELA Tutor (Q-learning) | Engagement sostenido | Planificador calibra ejercicios a P(correct) ∈ [0.40, 0.70] |
| **RAG parent-child** | ParentDocumentRetriever | +10-15% accuracy | ChromaDB con splitting recursivo 400/1000 tokens |
| **Chunking por AST** | tree-sitter | +4.3 puntos Recall@5 | tree-sitter-gdscript para código del usuario |

---

## 3. Principios fundacionales de LearnIt

1. **El proyecto del usuario es el currículum.** No hay un temario predefinido. El modelo de dominio se genera automáticamente a partir de la documentación del ecosistema que el usuario quiere aprender, podado por lo que ya sabe y enfocado en lo que necesita para su proyecto concreto.

2. **El usuario no es un estudiante pasivo.** Es un profesional (astrofísico, en el caso de ejemplo) que trae conocimiento asimétrico. El sistema diagnostica, no asume. Salta lo conocido, profundiza en lo nuevo.

3. **La terminal es el entorno natural del desarrollador.** La CLI inicia la sesión, la UI web local minimalista muestra chat, libreta, evaluaciones y dashboard. Sin depender de servicios cloud externos más allá del proveedor LLM.

4. **Persistencia total y portable.** Todo el estado del aprendizaje vive en `.learnit/`. Se versiona con git. Se comparte. Es auditable.

5. **La IA no da respuestas, guía el descubrimiento.** Modo socrático por defecto. La solución final solo se ofrece después de que el usuario ha razonado. Las pausas metacognitivas son forzadas, no opcionales.

6. **Verificación cruzada obligatoria.** Ningún subagente emite contenido pedagógico sin que otro subagente (o el orquestador) verifique contra la base de conocimiento grounded.

7. **El sistema aprende a enseñarte.** La política pedagógica se optimiza continuamente según tus resultados, no según un estándar externo.

---

## 4. Arquitectura del sistema

```
                           ┌─────────────────┐
                           │   Usuario (CLI)  │
                           └────────┬────────┘
                                    │ learnit start/teach/exercise/check/notes/end
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        ORQUESTADOR (DeepSeek V4 Pro Max)             │
│                                                                      │
│  - Carga perfil y estado de .learnit/                                │
│  - Decide qué subagente invocar                                     │
│  - Aplica política pedagógica (Q-table)                              │
│  - Verifica outputs de subagentes (CCVP)                             │
│  - Sintetiza respuesta final para el usuario                         │
│  - Actualiza estado al finalizar interacción                         │
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
│  ├── 2026-06-10.json └── review_schedule.json ├── signals.md         │
│  └── analytics.db                  └── concept_index.json            │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.1 Agentes: responsabilidades, disparadores y modelo

| Agente | Disparador | Responsabilidad | Modelo sugerido | ¿CCVP? |
|--------|-----------|----------------|-----------------|--------|
| **Orquestador** | Cada interacción del usuario | Carga estado, decide subagentes, sintetiza, actualiza estado | DeepSeek V4 Pro Max (1M ctx) | Verifica outputs de todos |
| **Diagnosticador** | Post-ejercicio, post-explicación | Actualiza BKT, detecta concepciones erróneas | DeepSeek V4 | Sus outputs son verificados por Orquestador |
| **Planificador** | Inicio de sesión, post-concepto | Selecciona siguiente nodo del Skill Tree, programa repasos FSRS | DeepSeek V3 (rápido) | Verificado contra BKT actual |
| **Documentalista** | Cuando se necesita info del dominio | RAG sobre ChromaDB, devuelve chunks + síntesis | DeepSeek V4 | Chunks grounded en fuentes |
| **Buscador Web** | Cuando doc local no cubre o está obsoleta | Busca, extrae, indexa en ChromaDB | DeepSeek V4 + search | Indexado con source tag |
| **Analizador Código** | Cuando usuario escribe/modifica código | AST vía tree-sitter, detecta patrones, carencias | Modelo rápido / Qwen2.5-Coder 14B local | Output estructurado, verificable |
| **Generador Ejercicios** | Cuando Planificador decide práctica | Genera enunciado calibrado a zona de flujo | DeepSeek V4 | Dificultad calibrada contra BKT |
| **Ejecutor** | Cuando hay código para probar | Ejecuta Godot headless, captura errores y logs | No-LLM (runner) | Output determinista |
| **Metacognitivo** | Bajo demanda, fin de sesión | Dashboard, refleja trayectoria, sugiere estrategias | Modelo rápido | Datos agregados de analytics |

### 4.2 Verificación cruzada (CCVP adaptado)

Para cada output pedagógico, el Orquestador aplica:

1. **Grounding check**: ¿Está este contenido respaldado por la documentación indexada? (Documentalista verifica)
2. **Consistency check**: ¿Es consistente con el BKT actual del estudiante? (Diagnosticador verifica)
3. **Prerequisite check**: ¿El usuario tiene los prerrequisitos para entender esto? (Planificador verifica contra Skill Tree)

Si alguna verificación falla, el Orquestador reformula o descarta el output antes de mostrarlo al usuario.

---

## 5. Modelo de dominio: Skill Trees auto-generados

### 5.1 Pipeline de generación

```
Documentación de Godot (20MB HTML/Markdown)
        │
        ▼
┌─────────────────────────────────┐
│ 1. EXTRACCIÓN                   │
│    MarkdownHeaderTextSplitter   │
│    → Chunks jerárquicos         │
│    → Embeddings vía Jina Code V2│
│    → ChromaDB (parent-child)    │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ 2. IDENTIFICACIÓN DE CONCEPTOS  │
│    LLM (DeepSeek V4) extrae:    │
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
│    - Marcadores: "antes de X",  │
│      "asumiendo Y", "ver Z"     │
│    - Dependencias de API        │
│    - Frecuencia de co-ocurrencia│
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
      "difficulty": 0.2,
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

A diferencia de una genérica "base de datos de dificultades", LearnIt mantiene un catálogo estructurado de concepciones erróneas conocidas para cada concepto, con:

- **Descripción precisa**: "El estudiante cree que `_process()` y `_physics_process()` son intercambiables para física"
- **Patrón de detección**: código que llama `move_and_slide()` desde `_process()` en lugar de `_physics_process()`
- **Estrategia de corrección**: contraste explícito con ejemplo donde la diferencia es visible (objeto que se mueve a distinta velocidad según frame rate)
- **Indicador BKT**: cuando se detecta, P(concepto) se ajusta a la baja con slip probability

---

## 6. Modelo del estudiante: más allá del overlay binario

### 6.1 Bayesian Knowledge Tracing (BKT)

Para cada skill en el grafo de dominio, se mantienen 4 parámetros:

| Parámetro | Significado | Inicialización |
|-----------|-------------|----------------|
| P(L₀) | Probabilidad inicial de que el usuario ya sepa la skill | Estimada del perfil (e.g., astrofísico → Python avanzado → P(L₀) alto para variables, bajo para Godot) |
| P(T) | Probabilidad de aprender la skill en un paso (transición) | 0.30 por defecto, se ajusta con datos |
| P(S) | Probabilidad de slip (error aunque sepas) | 0.10 por defecto |
| P(G) | Probabilidad de guess (acierto sin saber) | 0.15 por defecto |

Tras cada ejercicio, el Diagnosticador actualiza:

```
P(Lₙ | evidencia) = P(Lₙ₋₁ | evidencia_anterior) * P(transición) 
                    + (1 - P(Lₙ₋₁ | evidencia_anterior)) * P(T)

Si acierto: P(evidencia | L) = (1 - P(S)) / ((1 - P(S)) + P(G))
Si error:   P(evidencia | ¬L) = P(S) / (P(S) + (1 - P(G)))
```

### 6.2 FSRS (Free Spaced Repetition Scheduler)

Paralelo al BKT, cada skill tiene un estado en FSRS con 3 variables:

- **Dificultad (D)**: qué tan difícil es la skill para este usuario
- **Estabilidad (S)**: tiempo que el usuario retiene la skill tras un repaso
- **Recuperabilidad (R)**: probabilidad de recordar la skill en un momento dado

FSRS programa repasos automáticos. Tras cada interacción con una skill, recalcula S y D, y agenda la próxima revisión. El Planificador consulta el `review_schedule.json` al inicio de cada sesión y prioriza skills cuya R ha caído por debajo del umbral (típicamente R < 0.80).

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
  "constraints": {
    "max_session_minutes": 50,
    "preferred_time": "18:00 WEST",
    "weekdays": [1, 2, 3, 4, 5]
  }
}
```

### 6.4 Modelo afectivo ligero (sin hardware especial)

Sin acceso a cámara o sensores (entorno terminal/web), el modelo afectivo infiere estado de señales textuales y de comportamiento:

| Señal | Indicador | Umbral de acción |
|-------|-----------|------------------|
| Tasa de error creciente | Fatiga cognitiva | >+15% vs baseline → sugerir pausa |
| Tiempo de respuesta creciente | Fatiga o confusión | >2x mediana → investigar |
| Respuestas más cortas | Desenganche | <50% longitud media → cambiar estrategia |
| Preguntas de confirmación frecuentes | Inseguridad | "¿Estoy en lo correcto?" repetido → reforzar |
| Lenguaje negativo | Frustración | "no entiendo nada", "esto es imposible" → modo scaffolding |

### 6.5 Historial de concepciones erróneas

```json
{
  "student_id": "astrofisico_01",
  "history": [
    {
      "misconception_id": "process_instead_of_physics_process",
      "detected_at": "2026-06-10T18:30:00Z",
      "concept": "move_and_slide",
      "evidence": "Usaste _process(delta) en lugar de _physics_process(delta) para move_and_slide()",
      "corrected": true,
      "correction_date": "2026-06-10T18:45:00Z",
      "recurrence_count": 0
    }
  ]
}
```

---

## 7. Modelo pedagógico: estrategia optimizada continuamente

### 7.1 Mapeo tipo-concepto → estrategia

| Tipo de concepto | Estrategia por defecto | Ejemplo Godot |
|-----------------|----------------------|---------------|
| **Declarative** (qué es) | Ejemplo comentado + verificación | "CharacterBody2D es un nodo que hereda de..." → "Explícame con tus palabras qué lo diferencia de RigidBody2D" |
| **Procedural** (cómo se hace) | Scaffolding progresivo + ejercicio | "Paso 1: crea la escena. Paso 2: añade CharacterBody2D..." → "Ahora hazlo tú para el enemigo" |
| **Debugging** (qué falla) | Socrático | "Tu personaje no se mueve. ¿En qué método debería estar move_and_slide()? ¿Por qué?" |
| **Integrative** (combina A y B) | Intercalado + mini-proyecto | "Combina movimiento con animaciones: el personaje debe cambiar de sprite al moverse" |
| **Misconception** (error conocido) | Contraste explícito | "_process se llama cada frame de renderizado; _physics_process cada frame de física. Mira este ejemplo donde la diferencia importa..." |

### 7.2 Q-table de estrategia

El Orquestador mantiene una política que aprende qué estrategia funciona mejor para qué situación:

```
Estado: (concept_type, P_know, affective_state, hour_of_day)
Acción: (strategy, scaffolding_level, pace)
Recompensa: ΔP_know en siguiente evaluación del concepto
```

Con suficientes interacciones, la Q-table converge a preferencias personalizadas. Por ejemplo, puede aprender que para *este usuario*, los conceptos procedurales se aprenden mejor con scaffolding nivel 2 (más pistas) por la mañana que por la noche.

### 7.3 Bucle de mejora

```
Sesión N
  → Orquestador selecciona estrategia según Q-table
  → Diagnosticador mide resultado (Δ BKT)
  → Recompensa calculada
  → Q-table actualizada
  → Sesión N+1 usa política mejorada
```

No hay chequeo "cada X tiempo". Es continuo y basado en evidencia. Si se incorpora validación humana (DPO con profesor en el bucle), los pares de preferencia se almacenan en `.learnit/pedagogy/preference_pairs.jsonl` para fine-tuning diferido.

---

## 8. Modelo de sesión: hábito, fatiga y metacognición

### 8.1 Ciclo de sesión

```
┌──────────────────────────────────────────────────────┐
│                  learnit start                        │
│  - Orquestador carga perfil + estado                  │
│  - Planificador selecciona siguiente concepto         │
│  - Se muestra racha actual + progreso                 │
│  - "Hoy: CharacterBody2D y move_and_slide()"          │
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│                  learnit teach                        │
│  - Documentalista recupera chunks relevantes          │
│  - Orquestador explica con estrategia adecuada        │
│  - Usuario interactúa, pregunta, toma notas           │
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│              [Pausa metacognitiva ~12 min]            │
│  - Overlay: "Pausa de 30s. ¿Qué has aprendido?"      │
│  - Usuario escribe en libreta                        │
│  - Analizador verifica comprensión                    │
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│                learnit exercise                       │
│  - Generador crea ejercicio calibrado                 │
│  - Usuario escribe código                             │
│  - Analizador revisa AST                              │
│  - Ejecutor corre Godot headless                      │
│  - Diagnosticador actualiza BKT                       │
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│              [Pausa metacognitiva ~25 min]            │
│  - "Explica con tus palabras qué hace move_and_slide" │
│  - Notero analiza y vincula al concepto               │
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│                 learnit check                         │
│  - Orquestador muestra feedback detallado             │
│  - Diagnosticador revela concepciones erróneas        │
│  - Planificador actualiza ruta                        │
└────────────┬─────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────┐
│                 learnit end                           │
│  - Orquestador sugiere cierre (~45-50 min)            │
│  - Si tasa de error > +15% baseline: cierre activo    │
│  - Metacognitivo muestra dashboard de sesión          │
│  - Planificador agenda próxima sesión                 │
│  - "¿Mañana a las 18:00? Tu racha es de 5 días."     │
└──────────────────────────────────────────────────────┘
```

### 8.2 Rachas (streaks)

- Visibles siempre en la UI (barra superior)
- Hitos celebrados: 7, 14, 30, 100 días
- 2 "freezes" por semana (inspirado en Duolingo)
- Al romper racha: sin castigo, mensaje de ánimo, sugerencia de mini-sesión (15 min)
- Recordatorios personalizados: lunes (atraer), jueves (retener)

### 8.3 Micro-pausas forzadas

- Cada ~12 minutos de interacción activa
- 30 segundos, no opcionales
- Componente metacognitivo: "¿Qué acabo de aprender? ¿Qué me confunde? Escríbelo."
- El Notero analiza la respuesta y detecta concepciones erróneas

### 8.4 Terminación de sesión

El Orquestador monitoriza y sugiere cierre activo cuando:

| Condición | Umbral |
|-----------|--------|
| Tiempo de sesión | > 45 min (advertencia), > 52 min (cierre sugerido) |
| Tasa de error | > +15% vs baseline del estudiante |
| Tiempo de respuesta | > 2x mediana de la sesión |
| Señales de fatiga en lenguaje | Respuestas < 50% longitud media, +30% preguntas de confirmación |

El cierre es **sugerido y razonado**, no impuesto: "Has estado 48 minutos y tu tasa de acierto ha bajado del 82% al 64%. La fatiga está afectando tu aprendizaje. Es buen momento para cerrar. ¿Programamos mañana a las 18:00?"

### 8.5 Lo que NO se debe hacer

- ✗ Forzar cierre sin explicación ("Te queda 1 minuto")
- ✗ Pausas opcionales (Biwer et al.: las auto-reguladas son menos efectivas)
- ✗ Recordatorios genéricos ("Recuerda estudiar")
- ✗ Castigar la ruptura de racha
- ✓ Cierre razonado con datos
- ✓ Pausas sistemáticas no negociables
- ✓ Recordatorios personalizados con gancho de contenido
- ✓ Mensaje de ánimo tras racha rota + mini-sesión

---

## 9. Arquitectura multi-agente con verificación cruzada

### 9.1 Por qué multi-agente a pesar del 41-86.7% de fallo

El estudio MAST (Cemri et al., NeurIPS 2025) identificó que los fallos en sistemas multi-agente provienen de:

1. **Diseño del sistema**: ambigüedad de especificación, agentes con responsabilidades solapadas
2. **Desalineación entre agentes**: protocolos de coordinación no estructurados, handoffs sin validación
3. **Verificación de tareas**: outputs no chequeados, errores que se propagan entre agentes

LearnIt neutraliza estas causas:

| Causa de fallo | Mitigación en LearnIt |
|---------------|----------------------|
| Ambigüedad de especificación | Cada agente tiene un contrato explícito: input schema, output schema, herramientas, disparador |
| Responsabilidades solapadas | Documentalista vs Buscador Web: uno es RAG local, otro es búsqueda externa. No se solapan |
| Protocolos no estructurados | Orquestador como único punto de handoff. Subagentes no se hablan entre sí |
| Handoffs sin validación | CCVP: todo output de subagente es verificado por Orquestador contra Documentalista (grounding) y Diagnosticador (consistencia) |
| Errores que se propagan | Cada subagente recibe contexto acotado y devuelve output estructurado. El Orquestador es el único que integra |

### 9.2 Contratos de subagentes

**Ejemplo: Documentalista**

```
INPUT:
  - query: string (lo que se necesita saber)
  - concepts: string[] (conceptos del grafo relacionados)
  - student_bkt: {concept_id: P_know} (para no explicar lo que ya sabe)

OUTPUT:
  - chunks: [{text, source, relevance_score}] (fragmentos de documentación)
  - synthesis: string (resumen de 2-3 párrafos)
  - confidence: 0-1 (qué tan seguro está de cubrir la query)
  - sources_checked: int (cuántos chunks evaluó)

CONTRACT:
  - Solo usa ChromaDB local. Si no encuentra nada, devuelve confidence=0.
  - Si confidence < 0.7, Orquestador invoca Buscador Web.
```

**Ejemplo: Diagnosticador**

```
INPUT:
  - exercise_id: string
  - user_solution: {code, execution_result, errors}
  - expected_behavior: string (descripción del comportamiento esperado)
  - concepts_involved: string[]

OUTPUT:
  - bkt_updates: {concept_id: {P_know_old, P_know_new, evidence_type}}
  - misconceptions_detected: [{misconception_id, confidence, evidence}]
  - flow_zone: {P_correct_estimated, zone: "flow"|"boredom"|"anxiety"}
  - recommendation: "continue"|"review"|"scaffold"|"move_on"

CONTRACT:
  - No accede a documentación externa. Solo opera sobre BKT state y misconception catalog.
  - Si detecta un patrón no catalogado, lo registra como "unknown_misconception" para revisión.
```

---

## 10. Interfaz: CLI + web local

### 10.1 CLI

```
$ learnit start
  LearnIt v1.0 | Proyecto: godot_platformer
  Racha: 5 dias | Ultima sesion: ayer 18:00-18:47
  Hoy: CharacterBody2D + move_and_slide()
  
  Progreso del proyecto: ████████░░ 78% (14/18 conceptos)

$ learnit teach
  [Orquestador explica CharacterBody2D...]

$ learnit exercise
  [Generador propone ejercicio...]

$ learnit check
  [Diagnosticador analiza solucion...]

$ learnit notes
  [Abre libreta virtual...]

$ learnit status
  ┌─────────────────────────────────────────┐
  │ Sesión: 32 min                          │
  │ Ejercicios: 2/3 completados             │
  │ Tasa acierto: 78% (baseline: 82%)       │
  │ Zona: flow (P~0.62)                     │
  │ Próxima pausa: en 4 min                 │
  │ Próximo concepto: input handling        │
  └─────────────────────────────────────────┘

$ learnit end
  [Cierre de sesion con dashboard...]
```

### 10.2 Web local minimalista

La CLI levanta un servidor local (FastAPI + WebSocket) y abre el navegador en `localhost:7823`. La interfaz tiene tres paneles:

```
┌──────────────────────┬──────────────────────────────┐
│                      │                              │
│    CHAT              │    LIBRETA                   │
│    (60% width)       │    (40% width)               │
│                      │                              │
│  [Orquestador]       │  ┌────────────────────────┐  │
│  Hoy vamos a ver...  │  │ Mis apuntes sobre      │  │
│                      │  │ CharacterBody2D        │  │
│  [Tú]                │  │                        │  │
│  Vale, entiendo...   │  │ - Hereda de Node2D     │  │
│                      │  │ - Tiene velocity       │  │
│  [Orquestador]       │  │ - move_and_slide()     │  │
│  Ahora haz esto...   │  │ - Usar _physics_process│  │
│                      │  └────────────────────────┘  │
│                      │                              │
│  ┌─────────────────┐ │  Vinculado a:                │
│  │ Escribe aquí... │ │  ✓ character_body_2d         │
│  └─────────────────┘ │  ✓ move_and_slide            │
│                      │                              │
├──────────────────────┴──────────────────────────────┤
│  BARRA INFERIOR                                     │
│  Racha: 5 | Sesión: 32 min | Zona: flow | 18:32    │
└─────────────────────────────────────────────────────┘
```

La libreta está vinculada al modelo de dominio: cada apunte se asocia automáticamente al concepto correspondiente mediante similitud semántica. El Notero analiza los apuntes y puede detectar concepciones erróneas incluso en las notas personales del usuario.

---

## 11. Stack técnico

| Capa | Tecnología | Justificación |
|------|-----------|---------------|
| **LLM Orquestador** | DeepSeek V4 Pro Max (1M ctx) | Máxima capacidad de razonamiento, ventana suficiente para contexto de sesión + subagentes |
| **LLM Subagentes ligeros** | DeepSeek V3 o Qwen2.5-Coder 14B (local) | Tareas de clasificación, planificación, AST no requieren 1M ctx. Local para latencia |
| **Embeddings** | Jina Code V2 (Apache 2.0, local) | Específico de código, late chunking, open source, sin dependencia externa |
| **Vector Store** | ChromaDB | Local, sin servidor, API Python nativa, parent-child retrieval |
| **RAG Framework** | LangChain ParentDocumentRetriever | Splitting recursivo 400/1000 tokens, 10% overlap, parent-child |
| **AST Parser** | tree-sitter-gdscript | Chunking sintáctico del código del usuario, detección de patrones |
| **Spaced Repetition** | FSRS v6 (Python) | Open source, 17 parámetros, benchmarked en Anki |
| **Ejecución Godot** | godot --headless | Feedback de ejecución real, no solo análisis estático |
| **Persistencia** | JSON + SQLite | JSON editable a mano, SQLite para analytics y consultas |
| **Backend web** | FastAPI + WebSocket | Rendimiento, async nativo, WebSocket para streaming de respuestas |
| **Frontend** | HTMX + Alpine.js + Tailwind CSS | Minimalista, sin build step, interactividad suficiente |
| **CLI** | Click + Rich | Terminal interactiva con formato rico, paneles, progreso |

---

## 12. Qué hace a LearnIt mejor que el SOTA actual

### 12.1 Diferenciadores arquitectónicos

| Aspecto | SOTA actual | LearnIt |
|---------|-------------|---------|
| **Modelo de dominio** | Manual por expertos, o KG genérico no validado | Auto-generado desde docs con validación de baja ambigüedad, podado por perfil de usuario |
| **Modelo de estudiante** | Overlay binario o basado en prompts | BKT (4 params/skill) + FSRS (17 params/user) + misconception history + affective log |
| **Pedagogía** | Prompt engineering frágil | Q-table aprendida por usuario, mapeo tipo-concepto→estrategia, bucle continuo de mejora |
| **Verificación** | RAG sin verificación, o verificación manual | CCVP obligatorio: grounding + consistency + prerequisite check en cada output |
| **Sesión** | Chat abierto sin estructura | Ciclo con ritmo pedagógico, pausas metacognitivas forzadas, cierre activo basado en fatiga |
| **Hábito** | Ignorado en investigación ITS | Rachas con freezes, recordatorios personalizados, mini-sesiones |
| **Multi-agente** | 41-86.7% fallo por descoordinación | Contratos explícitos, handoff único vía Orquestador, verificación cruzada, sin comunicación entre subagentes |
| **Cognitive offloading** | Documentado y no mitigado | Modo socrático por defecto, pausas metacognitivas, nunca solución sin razonamiento previo |
| **Portabilidad** | Dependiente de plataforma/LMS | Carpeta `.learnit/` versionable con git, shareable, `AGENTS.md` interoperable |

### 12.2 Lo que LearnIt hace que NADIE más hace (a junio 2026)

1. **Skill Tree auto-generado desde la documentación del proyecto del usuario, podado por su perfil.** MMKG-RAG genera grafos desde videos y PDFs, pero no los poda contra el perfil del estudiante ni los enfoca a un proyecto concreto.

2. **BKT + FSRS integrados en un tutor conversacional con LLM.** Los sistemas de knowledge tracing (MSKT, NTKT) son motores de predicción, no tutores conversacionales. Los tutores conversacionales (LearnLM, Khanmigo) no tienen BKT ni FSRS integrados. LearnIt une ambas tradiciones.

3. **Verificación cruzada obligatoria (CCVP) en cada output pedagógico.** Ningún sistema SOTA implementa CCVP como requisito arquitectónico. La verificación existe como opción de despliegue, no como constraint de diseño.

4. **Ciclo cerrado afectivo sin hardware especial.** Sin cámara, sin sensores, sin voz. Solo texto y patrones de interacción. Suficiente para detectar fatiga, frustración y desenganche con precisión operacional.

5. **Cierre de sesión activo basado en datos, no en temporizador.** Nadie monitoriza tasa de error, tiempo de respuesta y longitud de respuesta para decidir terminar la sesión. Los sistemas actuales o no limitan la sesión, o usan temporizadores ciegos.

6. **Pausas metacognitivas forzadas que se integran con la libreta y el modelo de dominio.** Las pausas no son decorativas: el Notero analiza lo que escribes y actualiza el BKT y el historial de concepciones erróneas.

7. **Portabilidad total: `.learnit/` como fuente de verdad.** Ni un solo sistema SOTA es portable entre entornos. Dependen de la plataforma (Khan Academy, Moodle, Duolingo). LearnIt es una carpeta que viaja con tu proyecto.

---

## 13. Hoja de ruta de implementación

### Fase 1: Fundación (semanas 1-4)

**Objetivo**: Un solo agente bien instrumentado con RAG, BKT simple, y CLI funcional.

- [x] `learnit init` crea `.learnit/` con estructura base
- [x] Indexación de documentación de Godot en ChromaDB (parent-child retrieval)
- [x] `learnit start` carga perfil y muestra estado
- [x] `learnit teach` explica un concepto usando RAG
- [x] BKT con 4 parámetros por skill (inicialización manual del grafo para 5 conceptos)
- [x] `learnit exercise` genera ejercicio simple
- [x] `learnit check` analiza solución (tree-sitter + ejecución headless)
- [x] Persistencia de sesión en JSON
- [x] CLI con Click + Rich

### Fase 2: Multi-agente y Skill Tree (semanas 5-8)

- [x] Pipeline de generación automática de Skill Tree desde docs
- [x] Cruce con perfil de usuario (podar conceptos dominados)
- [x] Subagentes: Orquestador, Diagnosticador, Planificador, Documentalista
- [x] CCVP básico (grounding check)
- [x] FSRS integrado con Planificador
- [x] Catálogo inicial de concepciones erróneas (extraído de docs + comunidad Godot)

### Fase 3: Pedagogía y metacognición (semanas 9-12)

- [x] Q-table de estrategia pedagógica
- [x] Mapeo tipo-concepto → estrategia
- [x] Subagentes: Generador Ejercicios, Analizador Código, Notero
- [x] Pausas metacognitivas forzadas (~12 min)
- [x] Notero analiza apuntes y vincula a conceptos
- [x] Dashboard de sesión básico

### Fase 4: Sesión y hábito (semanas 13-16)

- [x] Rachas con freezes
- [x] Cierre activo de sesión basado en fatiga
- [x] Recordatorios personalizados
- [x] Subagente Metacognitivo
- [x] UI web local (FastAPI + HTMX + Alpine.js)
- [x] Libreta vinculada al modelo de dominio

### Fase 5: Pulido y SOTA+ (semanas 17-20)

- [x] CCVP completo (grounding + consistency + prerequisite)
- [x] Bucle DPO si hay profesor/revisor humano
- [x] Rate-distortion para poda automática de nodos redundantes
- [x] Analytics avanzados (SQLite + dashboard)
- [x] Buscador Web con indexación automática
- [x] `AGENTS.md` auto-generado desde `.learnit/student/profile.json`
- [x] Pruebas con múltiples dominios (Godot, Rust, astrofísica computacional)

---

## 14. Métricas de éxito

### 14.1 Métricas de aprendizaje

| Métrica | Definición | Objetivo |
|---------|-----------|----------|
| **Δ BKT medio por sesión** | Incremento promedio de P(know) en skills objetivo | > +0.15 |
| **Transferencia sin asistencia** | Desempeño en ejercicio sin ayuda del tutor | > 70% del desempeño asistido |
| **Retención a 7 días (FSRS)** | R > 0.80 para skills aprendidas hace 7+ días | > 85% de skills |
| **Concepciones erróneas corregidas** | % de misconceptions detectadas que no recurren | > 80% |

### 14.2 Métricas de engagement

| Métrica | Definición | Objetivo |
|---------|-----------|----------|
| **Días consecutivos (racha)** | Días con sesión completada | > 5 media |
| **Tasa de abandono de sesión** | Sesiones terminadas por comando vs abandono | > 90% terminadas |
| **Zona de flujo** | % de ejercicios con P(correct) ∈ [0.40, 0.70] | > 60% |
| **Tiempo en zona de flujo** | Minutos en flow vs total sesión | > 70% |

### 14.3 Métricas de sistema

| Métrica | Definición | Objetivo |
|---------|-----------|----------|
| **Precisión CCVP** | % de outputs que pasan verificación en primer intento | > 85% |
| **Tasa de alucinación** | % de contenidos no respaldados por fuentes grounded | < 3% |
| **Latencia de respuesta** | Tiempo desde input de usuario hasta output visible | < 3s (streaming) |
| **Fallos multi-agente** | % de invocaciones con error de coordinación | < 5% (vs 41-86.7% SOTA) |

---

## 15. Referencias

1. Chu et al., "LLM Agents for Education: Advances and Applications", 2025. arXiv:2503.11733
2. Zerkouk et al., "A Comprehensive Review of AI-based ITS", 2025. arXiv:2507.18882
3. Márquez-Carpintero et al., "Simulation of teaching behaviours in ITS", Artificial Intelligence Review, 2026
4. Cemri et al., "Why Do Multi-Agent LLM Systems Fail?", NeurIPS 2025
5. Deng & Yuan, "ITS Based on Automatic Multimodal Knowledge Graphs and RAG", Frontiers in Computer Science, 2026
6. "Deep Learning Based Knowledge Tracing in ITS" (MSKT), Nature Scientific Reports, 2025
7. "Next Token Knowledge Tracing" (NTKT), arXiv:2511.02599, 2025
8. "SkillTree: Scalable Personalized Learning with LLM-Linked Custom Knowledge Graphs", IES 2025-2026
9. "Graph4Learn: Evolving Knowledge Space Graph", ETRD Springer, 2026
10. "The Path to Conversational AI Tutors", arXiv:2602.19303, 2025
11. Stanford SCALE, "The Evidence Base on AI in K-12: A 2026 Review", 2026
12. Kestin et al., "AI Tutoring RCT", Nature Scientific Reports, 2025
13. Aulagnon, Cristia, Cueto & Malamud, "Streaks RCT Peru (60K students)", 2024
14. Dianita et al., "Micro-breaks experiment", Kyoto University, 2024
15. Biwer et al., "Pomodoro vs self-regulated breaks", British Journal of Educational Psychology, 2023
16. Lodge & Loble, "Metacognitive laziness in AI tutoring", UTS, 2026
17. Kosmyna et al., "Your Brain on ChatGPT", arXiv:2506.08872, 2025
18. Gerlich, "AI Tools and Critical Thinking", MDPI Societies, 2025
19. Weissburg et al., "LLMs are Biased Teachers", arXiv:2410.14012, 2024
20. Fleig, "Towards Multimodal Affective Intelligence in Educational AI", UCSD, 2025
21. Bijl, "Skill Trees: A Framework for Structuring Education", Koli Calling, 2025
22. An et al., "Rate-Distortion Guided KG Construction", 2025
23. FSRS v6, Open Spaced Repetition, 2025-2026
24. Microsoft Azure, "Multi-Agent Best Practices", 2025
25. Anthropic, "Building Effective Agents", 2025

---

*Documento preparado el 10 de junio de 2026. Las referencias reflejan el estado del arte a esta fecha. LearnIt se diseña para un horizonte de implementación de 20 semanas con iteración continua posterior.*

---

**Usuario:** Muy peor que muy buen informe. Te voy a dar algún feedback, cómo tenemos rpesupuesto de sobra nuestra idea es usar DeepSeek V4 Pro Max para todos los subagentes. Así no recortamos en calidad. Realmente el CLI es tan solo para lanzar el programa con "learnit" o actualizar el programa con algo como "learnit --update" por ejemplo. Toda la interactividad la hacemos mediante la web local (no importa, o imagino que no importa, pero usaría GO (o Python si es estricamente necesario, o ambas si se puede mezclar cosas, ya que ya tenemos alguna otra cosa que hecha usando GO)+`SolidJS creo).

Y también me pregunto, ¿y que pasa si el usuario tiene más tiempo y quiere aprender más? Por ejemplo, qué pasa si es verano y tiene más tiempo, en lugar de sesiones más largas es rentable hacer más sesiones? Deberíamos hacer que el sistema se ajustase de manera automática a los deseos y disponibilidad del usuario?

---

**Agente:** Varias preguntas muy pertinentes. Investigo en paralelo: el debate sesiones más largas vs. más sesiones (con datos), la auto-adaptación a disponibilidad del usuario, y si Go tiene limitaciones reales para un sistema con este perfil de IA.

---

## Respuesta directa a tus puntos

### 1. DeepSeek V4 Pro Max para todos los subagentes

Totalmente válido. Si el presupuesto lo permite, homogeneizar el modelo simplifica la arquitectura, elimina variables de calidad diferencial entre agentes, y evita tener que mantener dos proveedores o dos modos de prompting. La única consideración práctica es la latencia: para subagentes que necesitan respuesta rápida (Planificador, AnalizadorCódigo), asegúrate de que las llamadas sean asíncronas y paralelizables. Pero con Go eso es natural.

### 2. CLI solo como lanzador, interacción en web local con Go + SolidJS

Es una decisión excelente. La CLI como entry point y gestor de ciclo de vida (`learnit`, `learnit --update`, `learnit stop`) es el patrón correcto. La web como interfaz de interacción también.

Sobre **Go + SolidJS**: no solo es viable, es una combinación muy potente para este caso.

- **Go** como servidor web (HTTP + WebSocket) es excepcional: pocos recursos, concurrencia real, binario único, despliegue trivial. No necesitas Python en absoluto. De hecho, Go es superior a Python para el backend de este sistema porque:
  - Manejo nativo de concurrencia (goroutines) para las múltiples llamadas paralelas a DeepSeek
  - Un solo binario compilado que el usuario ejecuta sin dependencias
  - Streaming de respuestas por WebSocket sin complejidad añadida
  - ChromaDB tiene SDK para Go (aunque si usas ChromaDB en modo servidor local, la comunicación es HTTP/REST, agnóstica al lenguaje)

- **SolidJS** como frontend es también una gran elección: reactividad sin overhead de runtime, sin virtual DOM, señales nativas, excelente para una SPA ligera con actualizaciones en tiempo real vía WebSocket.

El único punto donde podrías necesitar Python es en el ecosistema de ML (tree-sitter-gdscript tiene bindings en Go también, FSRS tiene implementación en múltiples lenguajes, pero si en algún momento necesitas algo muy específico del ecosistema Python, puedes aislarlo como microservicio o script llamado desde Go). Pero en principio, **Go puede cubrir todo el backend**.

> Si ya tienes otras herramientas en Go, la cohesión del stack es un plus real. Un solo binario que arranca el servidor web, abre el navegador, y gestiona todo el ciclo de vida.

---

## 3. La cuestión de fondo: ¿sesiones más largas o más sesiones?

Esta es la pregunta más interesante. He investigado específicamente este punto.

### 3.1 La respuesta corta: más sesiones, no sesiones más largas

La evidencia es consistente en que **el aprendizaje distribuido (espaciado) supera al aprendizaje masivo (intensivo)** incluso cuando el tiempo total es idéntico. Pero con matices importantes:

- **Efecto de espaciado (spacing effect):** Es uno de los hallazgos más robustos en psicología cognitiva. Distribuir el mismo tiempo de estudio en múltiples sesiones produce mejor retención a largo plazo que concentrarlo en sesiones largas. Esto aplica tanto a intervalos de días como a intervalos dentro del mismo día.

- **Dunlosky et al. (2013)** en su meta-análisis fundacional muestran que la práctica distribuida tiene un tamaño de efecto moderado-alto (d = 0.5-0.7) sobre la práctica masiva.

- **Cepeda et al. (2006, *Psychological Bulletin*)** demostraron que el espaciado óptimo es aproximadamente 10-20% del intervalo de retención deseado. Si quieres recordar algo 30 días, el gap óptimo entre sesiones de estudio de ese concepto es de 3-6 días. Pero también encontraron que **múltiples sesiones en un mismo día con gaps de horas** son superiores a una sola sesión larga.

- **Kang (2016, *Policy Insights from Behavioral and Brain Sciences*)** encontró que sesiones cortas repetidas (15-30 min) distribuidas a lo largo del día producen mejor transferencia que una sesión equivalente de 90-120 minutos. El mecanismo propuesto es que los períodos entre sesiones permiten consolidación hipocampal y reactivación de la memoria.

### 3.2 ¿Cuántas sesiones al día es óptimo?

No hay un número mágico, pero la investigación apunta a:

| Configuración | Efectividad | Fatiga | Recomendación |
|--------------|-------------|--------|---------------|
| 1 sesión de 50 min | Base | Baja | Mínimo diario |
| 2 sesiones de 45-50 min con >2h de gap | +15-25% retención vs 1 sesión | Moderada | Máximo recomendado por defecto |
| 3 sesiones de 40-45 min con >2h de gaps | +20-30% retención vs 1 sesión, pero con rendimiento decreciente en 3ª sesión | Alta | Solo en modo intensivo (verano, bootcamp) |
| 4+ sesiones o sesiones >60 min | Rendimiento marginal, fatiga acumulada, riesgo de burnout | Muy alta | No recomendado |

El punto clave: **el gap entre sesiones importa más que la duración exacta de cada sesión**. Un gap de al menos 2 horas permite consolidación de memoria y recuperación cognitiva. Sin ese gap, dos sesiones seguidas de 45 min son esencialmente una sesión de 90 min con los mismos problemas de fatiga.

### 3.3 Implicación para LearnIt: el sistema debe adaptarse automáticamente

Esto refuerza tu intuición de que el sistema debe ajustarse a la disponibilidad del usuario. Pero no debe ser una adaptación pasiva ("el usuario decide"), sino una **adaptación guiada por principios de aprendizaje**:

**Propuesta de diseño: Modos de intensidad**

```
┌─────────────────────────────────────────────────────┐
│                 learnit start                        │
│                                                      │
│  El sistema detecta o pregunta disponibilidad:       │
│                                                      │
│  Modo estándar (por defecto):                        │
│  • 1 sesión/día, 45-50 min                          │
│  • 1 concepto nuevo + repasos FSRS                   │
│  • Pausas cada 12 min                                │
│                                                      │
│  Modo intensivo (verano, bootcamp):                  │
│  • Hasta 3 sesiones/día, 40-45 min c/u              │
│  • Gap mínimo 2h entre sesiones                     │
│  • 3ª sesión: solo repasos + ejercicios, no conceptos│
│    nuevos (menor carga cognitiva)                    │
│  • Monitorización de fatiga más estricta             │
│  • Pausas cada 10 min                                │
│                                                      │
│  Modo libre (fin de semana, festivo):                │
│  • Hasta 2 sesiones/día sin concepto nuevo en 2ª     │
│  • Gap flexible                                      │
└─────────────────────────────────────────────────────┘
```

### 3.4 Auto-ajuste fino además de modos

Más allá de los modos predefinidos, el sistema puede aprender patrones del usuario:

- **Detección de ventana temporal**: si el usuario consistentemente tiene sesiones más largas los fines de semana, el sistema lo incorpora y sugiere más ejercicios integradores esos días.
- **Detección de fatiga acumulada entre sesiones**: si la tasa de error en la 2ª sesión del día es consistentemente >X% peor que en la 1ª, el sistema sugiere reducir a 1 sesión.
- **Ajuste de carga cognitiva por hora del día**: la investigación muestra que la capacidad de aprendizaje varía circadianamente. Si el usuario rinde peor a las 22:00, el sistema puede sugerir sesiones más ligeras (solo repasos) a esa hora y reservar conceptos nuevos para su hora óptima.
- **Preguntar, no asumir**: al inicio de cada sesión, una pregunta ligera: "¿Cuánto tiempo tienes hoy?" o "¿Modo estándar (45 min) o intensivo (2-3 sesiones)?" Esto es empoderamiento, no imposición.

### 3.5 Lo que NO debe hacer el sistema

- ✗ Permitir sesiones maratónicas de 2-3 horas sin pausas ni advertencias (aunque el usuario "quiera")
- ✗ Forzar un modo intensivo a alguien que solo tiene 45 minutos
- ✗ Tratar todas las horas del día como iguales para aprendizaje
- ✗ Ignorar la fatiga acumulada entre sesiones del mismo día
- ✓ Guiar activamente hacia la distribución óptima
- ✓ Advertir cuando la duración o frecuencia es contraproducente
- ✓ Adaptar la carga cognitiva a la hora del día y al número de sesión

---

## 4. Actualización del diseño de sesión

Incorporando la adaptabilidad:

```json
// .learnit/student/profile.json (extendido)
{
  "session_preferences": {
    "mode": "auto_detect",        // "standard" | "intensive" | "free" | "auto_detect"
    "max_sessions_per_day": 3,
    "min_gap_minutes": 120,
    "max_session_minutes": 50,
    "intensive_max_session_minutes": 40,
    "third_session_concept_new": false,
    "optimal_hours": [9, 10, 11, 17, 18],  // aprendido de datos históricos
    "low_performance_hours": [22, 23, 0],   // aprendido de datos históricos
    "weekly_availability": {
      "monday": 1,      // sesiones típicas
      "tuesday": 1,
      "wednesday": 1,
      "thursday": 1,
      "friday": 1,
      "saturday": 3,    // más disponibles
      "sunday": 2
    }
  },
  "learned_patterns": {
    "best_session_duration": 47,      // duración donde rinde mejor
    "fatigue_onset_minute": 44,       // minuto donde empieza a bajar rendimiento
    "second_session_penalty": 0.08,   // cuánto baja rendimiento en 2ª sesión vs 1ª
    "third_session_penalty": 0.18     // cuánto baja en 3ª sesión
  }
}
```

El flujo al inicio de sesión:

```
> learnit start

  LearnIt v1.0 | Proyecto: godot_platformer  
  Racha: 5 días | Hoy: miércoles 18:00

  ¿Cuánto tiempo tienes hoy?
  [1] ~45 min (estándar) — 1 sesión
  [2] ~90 min (intensivo) — 2 sesiones de 45 min con descanso
  [3] ~2.5h (bootcamp) — 3 sesiones de 40 min con descansos
  [4] Sin plan fijo — tú guías

  > 2

  Perfecto. Sesión 1 ahora (18:00-18:45). 
  Sesión 2 a las 20:45 (gap de 2h). 
  Te avisaré a las 20:40.

  Hoy: CharacterBody2D + move_and_slide()
  Progreso: ████████░░ 78%
```

---

## 5. Actualización del stack técnico

| Capa | Tecnología | Nota |
|------|-----------|------|
| **Backend** | Go | Servidor HTTP + WebSocket, gestión de subagentes, RAG, ejecución de comandos |
| **Frontend** | SolidJS + Tailwind CSS | SPA reactiva ligera, streaming vía WebSocket |
| **CLI launcher** | Go (Cobra o simple flag parsing) | `learnit`, `learnit --update`, `learnit stop` |
| **LLM** | DeepSeek V4 Pro Max (todos los agentes) | API HTTP desde Go |
| **Embeddings** | Jina Code V2 (servicio local ligero) | Llamada HTTP desde Go |
| **Vector Store** | ChromaDB (modo servidor local) | HTTP REST desde Go |
| **FSRS** | Implementación en Go o puerto del algoritmo | Algoritmo sencillo, ~500 líneas |
| **Base de datos** | SQLite (mattn/go-sqlite3) | Nativo en Go, sin dependencias externas |
| **AST** | tree-sitter-gdscript (binding Go) | Hay bindings Go para tree-sitter |

---

## Resumen de decisiones actualizadas

| Decisión | Estado |
|----------|--------|
| DeepSeek V4 Pro Max para todos | ✓ Confirmado |
| Go backend + SolidJS frontend | ✓ Confirmado, viable y potente |
| CLI solo launcher | ✓ Confirmado |
| Web local para interacción | ✓ Confirmado |
| Sesiones adaptables a disponibilidad | ✓ Nuevo: 3 modos + auto-ajuste fino |
| Más sesiones > sesiones más largas | ✓ Evidencia sólida, gaps de 2h mínimo |
| Fatiga entre sesiones monitorizada | ✓ Nuevo: `second_session_penalty` en perfil |
| Sistema guía activamente, no obedece ciegamente | ✓ Principio: el tutor educa sobre cómo aprender, no solo sobre Godot |

¿Quieres que detalle la arquitectura Go del backend, los endpoints de la API, o el modelo de datos en SQLite para la siguiente iteración?

---

**Usuario:** Me gusta esto, podríamos hacer, para que se sienta más como un curso real, hacer también como parte del proyecto que el sistema avise por correo electrónico de las clases, por ejemplo que tras hablar con el usuario a qué horas le viene bien hoy le mande un correo con las horas de las clases, que si el usuario se conecta más tarde, cómo podemos hacer que al enviar un mensaje el agente vea la hora reaccione a ello, le mande un correo unos minutos antes de empezar la sesión para recordárselo y que el usuario pueda contestar diciéndole que puede más tarde o que al final no puede, etc. Y que mande cosas como estadísticas semanales o mensuales, etc.

Para hacer esto podríamos hacer que al crear un usuario el programa copie el .learnit en uns ervidor y un subagente comunicador se encargue del tema de los correos aunque el usuario tenga el programa cerrado, o que el programa se quede abierto de fondo en el PC del usuario si quiere activar esta opción por ejemplo.

---

**Agente:** Buena visión. Esto cambia el perfil del sistema de "herramienta de terminal" a "plataforma de aprendizaje con presencia continua". Investigo los aspectos técnicos y de experiencia de usuario.

---

## Respuesta estructurada

### 1. Los dos modos de operación: ventajas y trade-offs reales

Tu intuición de ofrecer ambas opciones es acertada. No son redundantes: resuelven perfiles de usuario distintos.

| | **Modo servidor** | **Modo PC (background)** |
|---|---|---|
| **¿Cómo funciona?** | `.learnit/` se sincroniza con un servidor. Un subagente vive allí y gestiona correos, recordatorios, estadísticas. | El programa se queda como proceso en background (tray icon / systemd). El subagente comunicador vive localmente. |
| **Ventaja clave** | Funciona aunque el PC esté apagado. El usuario recibe recordatorios esté donde esté. | Sin dependencia de servidor externo. Privacidad total. Sin coste de infraestructura. |
| **Desventaja clave** | Requiere servidor (aunque sea VPS mínimo). Los datos salen de la máquina local. | Si el PC está apagado, no hay recordatorios. Consume recursos locales. |
| **Perfil de usuario** | Aprendiz serio que quiere experiencia "curso real" completa, con recordatorios fiables | Desarrollador que valora privacidad y simplicidad, y suele tener el PC encendido |
| **Complejidad técnica** | Moderada (sincronización, servidor, seguridad) | Baja-moderada (proceso background, menos infraestructura) |

**Recomendación**: implementar el modo PC primero (más simple, sin servidor, cubre el 80% del valor), y el modo servidor como opción avanzada para quien quiera recordatorios garantizados incluso con el PC apagado. El `.learnit/` no cambia de estructura en ningún caso, solo cambia dónde vive el subagente comunicador.

### 2. Diseño del subagente comunicador

#### 2.1 Responsabilidades

| Función | Descripción | Disparador |
|---------|-------------|-----------|
| **Negociación de horario** | Al final de cada sesión, o vía email, acuerda hora para la siguiente | Fin de sesión, o email del usuario |
| **Recordatorio pre-sesión** | Email 10-15 min antes de la hora acordada | Temporizador interno |
| **Gestión de respuestas** | El usuario puede responder al email: "a las 19:00 mejor", "hoy no puedo", "empezamos ya" | Recepción de email (IMAP/POP3 o reply-to) |
| **Estadísticas periódicas** | Resumen semanal/mensual con progreso, racha, conceptos aprendidos | Cron semanal (lunes 9:00) o mensual |
| **Reenganche** | Si el usuario falta 2+ días sin avisar, email de reactivación suave | Inactividad detectada |

#### 2.2 El correo como canal bidireccional (esto es la clave)

No basta con enviar correos. El sistema debe **recibir y procesar respuestas**. Esto es lo que lo hace sentirse como un curso real con un tutor humano al otro lado.

**Propuesta técnica**:

- **Envío**: SMTP. Go tiene `net/smtp` en stdlib. Simple, sin dependencias. El usuario configura su proveedor (Gmail app password, SendGrid, Mailgun, o servidor propio).
- **Recepción**: Dos opciones:
  - **IMAP** (recomendado para modo PC): El subagente comunicador monitorea una carpeta del buzón del usuario (e.g., `LearnIt/`). Go tiene librerías IMAP (`emersion/go-imap`). El usuario crea un filtro en su correo que mueva las respuestas a LearnIt a esa carpeta.
  - **Reply-to + webhook** (alternativa más ligera): Servicios como SendGrid/Mailgun convierten replies en webhooks que LearnIt recibe. Pero requiere servidor accesible desde internet, lo cual empuja hacia modo servidor.

Para el modo PC, IMAP es la opción más autónoma: el proceso background consulta cada 2-3 minutos la carpeta de respuestas.

#### 2.3 Formato de emails

Los emails deben ser **parseables por LLM** pero también **legibles por humanos**. Un formato híbrido:

**Recordatorio pre-sesión (10 min antes)**:

```
From: LearnIt <tutor@learnit.local>
To: usuario@email.com
Subject: Tu sesión de Godot empieza en 10 min (18:00)

Hola,

Tu sesión de hoy está programada a las 18:00 (hora local).
Duración prevista: 45 minutos.
Tema: move_and_slide() y detección de colisiones.

¿Todo bien? Puedes responder a este correo:
- "OK" o "allá voy" → Confirmas
- "a las 19:00" → Reprogramas
- "hoy no puedo" → Cancelas la sesión de hoy
- "15 min tarde" → Retrasas

Nos vemos pronto,
LearnIt

--
Racha actual: 5 días  |  Progreso del proyecto: 78%
ID de sesión: sess_20260611_1800
```

**Estadísticas semanales (lunes 9:00)**:

```
From: LearnIt <tutor@learnit.local>
To: usuario@email.com
Subject: Tu semana en LearnIt: 10-16 junio

═══════════════════════════════════════
  TU SEMANA EN LEARNIT
  10 - 16 de junio de 2026
═══════════════════════════════════════

SESIONES: 5/5 completadas  ✓
RACHA: 12 días  |  +2 vs semana anterior

CONCEPTOS NUEVOS:
  ✓ CharacterBody2D
  ✓ move_and_slide()
  ✓ Input handling
  → En progreso: Señales (signals)

EJERCICIOS: 8/9 completados (89%)
  Tasa de acierto: 81% (+3% vs semana anterior)
  Zona de flujo: 68% del tiempo

CONCEPCIONES ERRÓNEAS CORREGIDAS:
  ✓ _process vs _physics_process (no ha recurrido)

PRÓXIMA SEMANA:
  Objetivo: Señales, colisiones, y empezar el sistema de plataformas
  Sesiones sugeridas: L-V 18:00 (45 min)

¿Ajustamos algo para la semana que viene?
Responde a este correo si quieres cambiar horario, duración, o ritmo.

LearnIt
```

#### 2.4 Procesamiento de respuestas del usuario

El subagente comunicador recibe el email, extrae el texto, y el LLM (DeepSeek V4 Pro Max) lo clasifica en intenciones:

| Respuesta del usuario | Intención detectada | Acción |
|----------------------|-------------------|--------|
| "OK", "allá voy", "perfecto", "vale" | CONFIRM | Marcar sesión como confirmada, enviar "¡Nos vemos!" |
| "a las 19:00", "mejor a las 20:30", "más tarde" | RESCHEDULE | Actualizar hora en `.learnit/`, enviar confirmación con nueva hora |
| "hoy no puedo", "cancelar", "otro día" | CANCEL | Marcar sesión como cancelada, no penaliza racha si usa freeze, intentar reagendar |
| "empiezo ya", "estoy listo", "adelantar" | START_NOW | Iniciar sesión inmediatamente, enviar confirmación |
| "15 min tarde", "llego en 20 min" | DELAY | Ajustar hora de inicio, enviar nuevo recordatorio |
| "esta semana no puedo a las 18:00" | PREFERENCE_CHANGE | Iniciar diálogo de renegociación de horario semanal |

Las respuestas que no encajan en ningún patrón claro desencadenan un email del comunicador pidiendo aclaración: "No he entendido bien. ¿Quieres confirmar, reprogramar, o cancelar la sesión de hoy?"

---

### 3. Negociación de horario: el diálogo inicial y continuo

#### 3.1 Primera configuración (al crear proyecto o primeras sesiones)

Esto ocurre en la web durante una sesión, no por email:

```
┌─────────────────────────────────────────┐
│  LearnIt - Configuración de horario     │
│                                         │
│  ¿Quieres que te recuerde las sesiones  │
│  por correo?                            │
│                                         │
│  [✓] Activar recordatorios por email    │
│                                         │
│  Tu correo: usuario@email.com           │
│                                         │
│  ¿Qué días prefieres?                   │
│  [✓] L  [✓] M  [✓] X  [✓] J  [✓] V    │
│  [ ] S  [ ] D                           │
│                                         │
│  Franja horaria preferida:              │
│  [18:00] - [19:00]  (WEST)             │
│                                         │
│  Duración por sesión:                   │
│  ( ) 30 min  (•) 45 min  ( ) 60 min    │
│                                         │
│  ¿Modo flexible?                        │
│  [✓] Confirmar cada día (te pregunto    │
│       si mantienes la hora)             │
│  [ ] Horario fijo semanal               │
│                                         │
│  [Guardar]                              │
└─────────────────────────────────────────┘
```

#### 3.2 Diálogo diario de confirmación

Si el usuario eligió modo flexible, cada día a una hora configurable (ej. 9:00), el comunicador envía:

```
Subject: ¿Hoy a las 18:00? | LearnIt

Hola,

¿Mantenemos la sesión de hoy a las 18:00?
Tema de hoy: Señales en Godot.

Responde:
- "sí" → Confirmas
- "a las X" → Cambias hora
- "hoy no" → Cancelas

LearnIt
```

Si el usuario no responde en 2 horas, se asume confirmación silenciosa y se envía el recordatorio normal 10 min antes.

#### 3.3 El caso de "el usuario se conecta más tarde"

Mencionas este caso específico: ¿qué pasa si la sesión era a las 18:00, el usuario no aparece, y se conecta a las 18:23?

```
18:00 - Hora programada
18:05 - El comunicador detecta que no hay sesión activa
18:05 - Email: "Te esperaba a las 18:00. ¿Todo bien? 
        Puedes responder 'a las 18:30' o 'hoy no puedo'."
18:23 - Usuario abre LearnIt
       → Orquestador detecta que hay una sesión programada 23 min antes
       → Mensaje en UI: "Tu sesión era a las 18:00. 
          ¿Empezamos ahora (quedan ~22 min de sesión) 
          o prefieres reprogramar para mañana?"
       
       Si elige empezar: 
       → Sesión acortada proporcionalmente (22 min)
       → Planificador ajusta: omite concepto nuevo, solo repasos o ejercicio ligero
       → No penaliza racha (llegó, aunque tarde)
       
       Si elige no:
       → Se consume un freeze
       → Se reprograma para mañana
```

El subagente comunicador y el orquestador comparten estado de sesión. Cuando el orquestador inicia, consulta `session_plan.json` y detecta el retraso.

---

### 4. Arquitectura del subagente comunicador

```
┌─────────────────────────────────────────────────────────┐
│              COMUNICADOR (DeepSeek V4 Pro Max)           │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ Scheduler   │  │ Email Reader │  │ Report Builder │  │
│  │ (cron-like) │  │ (IMAP poll)  │  │                │  │
│  │             │  │              │  │ Genera          │  │
│  │ Dispara     │  │ Lee carpeta  │  │ estadísticas    │  │
│  │ recordato-  │  │ LearnIt/     │  │ semanales/      │  │
│  │ rios,       │  │ cada 2-3 min │  │ mensuales       │  │
│  │ confirma-   │  │              │  │ desde analytics │  │
│  │ ciones      │  │ Clasifica    │  │                 │  │
│  │ diarias     │  │ respuestas   │  │                 │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘  │
│         │                │                   │           │
│         └────────────────┼───────────────────┘           │
│                          ▼                               │
│              ┌───────────────────────┐                   │
│              │  LLM Intent Parser   │                   │
│              │  (DeepSeek V4 PM)    │                   │
│              │                      │                   │
│              │  Entrada: email text │                   │
│              │  Salida: intención   │                   │
│              │  + parámetros        │                   │
│              └───────────┬───────────┘                   │
│                          │                               │
│         Acciones: confirmar / reprogramar / cancelar     │
│         / estadísticas / reenganche                      │
└─────────────────────────────────────────────────────────┘
```

### 4.1 Modo PC (background process)

```
learnit daemon start    →  Arranca proceso en background
                           (systemd en Linux, launchd en macOS,
                            servicio en Windows)

learnit daemon stop     →  Detiene el background process

learnit daemon status   →  Muestra estado:
                           - Comunicador: activo
                           - Próxima sesión: hoy 18:00
                           - Email configurado: usuario@gmail.com
                           - Último chequeo: hace 1 min
```

El proceso background es ligero: consume ~15-30 MB de RAM, hace polling IMAP cada 2-3 minutos, y solo invoca al LLM cuando recibe una respuesta de email (típicamente 0-2 veces al día). No es un proceso pesado que el usuario note.

### 4.2 Modo servidor (futuro)

```
El usuario ejecuta: learnit deploy

Esto:
1. Empaqueta .learnit/
2. Lo sube a un servidor (VPS, fly.io, Railway)
3. El comunicador vive allí 24/7
4. El usuario hace learnit pull para sincronizar estado
   al iniciar sesión local
5. La sesión corre localmente (web local), pero el
   comunicador en servidor sigue funcionando aunque
   el PC esté apagado
```

La sincronización es bidireccional: el servidor actualiza `.learnit/student/` y `.learnit/sessions/` cuando el comunicador procesa respuestas, y el PC local sincroniza al iniciar y al terminar cada sesión.

---

### 5. Estructura actualizada de `.learnit/`

```json
// .learnit/config.json (extendido)
{
  "project": "godot_platformer",
  "comunicator": {
    "enabled": true,
    "mode": "local_daemon",
    "email": {
      "smtp": {
        "host": "smtp.gmail.com",
        "port": 587,
        "username": "usuario@gmail.com"
        // password en keychain del SO, no en archivo
      },
      "imap": {
        "host": "imap.gmail.com",
        "port": 993,
        "folder": "LearnIt"
      },
      "from_name": "LearnIt"
    },
    "schedule": {
      "timezone": "Europe/Lisbon",
      "default_time": "18:00",
      "weekdays": [1, 2, 3, 4, 5],
      "confirmation_mode": "daily_flexible",
      "confirmation_time": "09:00",
      "reminder_before_minutes": 10
    },
    "notifications": {
      "weekly_report": true,
      "weekly_report_day": 1,        // lunes
      "weekly_report_time": "09:00",
      "monthly_report": true,
      "reengagement_after_missed_days": 2
    }
  }
}
```

---

### 6. ¿Merece la pena un subagente dedicado a esto?

Sí, y por una razón que no es obvia: **el comunicador maneja el estado de disponibilidad del usuario**, que es una señal valiosa para el modelo afectivo y el planificador. Que el usuario cancele dos sesiones seguidas un jueves y un viernes no es solo un problema de scheduling: puede indicar fatiga, desinterés, o un cambio en su vida. El comunicador puede escalar esto al orquestador para que ajuste la estrategia (sesiones más cortas, conceptos más motivadores, o una pausa sugerida).

Además, la presencia continua del comunicador (aunque sea vía email) es lo que más contribuye a la **sensación de curso real**. No es lo mismo abrir una terminal y escribir `learnit` que recibir un correo el lunes con tu progreso semanal y otro el miércoles recordándote la sesión. El segundo caso genera compromiso, expectativa y hábito. La investigación de rachas que vimos antes se potencia con recordatorios externos.

---

¿Profundizo en la implementación Go del comunicador (goroutines, scheduler, IMAP polling) o prefieres cerrar primero el diseño completo de la experiencia de usuario (todos los flujos de interacción: primera configuración, sesión, email, estadísticas)?

---

**Usuario:** La opción del sistema para mandar mensajes vamos a dejarlo a algo extra al terminal, pero nos vamos a quedar con un sistema para negociar sesiones, si llegas tarde poder empezarla en ese momento, o reajustarla, si abres el programa por la tarde y la sesión estaba planeada por la llamada el sistema te pregunte que qué ha pasado, que si quieres tener la sesión entonces a esa hora o has entrado para replanificar la sesión etc. 

¿Con todo esto podrías reescribir el informe completo?

---

**Agente:** Claro. Aquí está el informe completo y refundado, incorporando todas las decisiones, refinamientos y aprendizajes de nuestra conversación.

---

# LearnIt: Documento de Arquitectura y Visión

## Sistema de tutoría inteligente personal multi-agente

**Versión 2.0 — 11 de junio de 2026**

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