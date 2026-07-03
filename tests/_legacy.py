"""Compat wrapper for tests that need old ReportStore API."""
from cognits.storage.database import Database
from cognits.storage.learner_state import LearnerStateRepository
from cognits.storage.messages import MessageRepository
from cognits.storage.notes import NoteRepository
from cognits.storage.pedagogical import PedagogicalPlanRepository
from cognits.storage.reports import ReportRepository
from cognits.storage.session_config import SessionConfigRepository
from cognits.storage.skills import SkillRepository
from cognits.storage.study_plans import StudyPlanRepository

class LegacyStore:
    """Compat wrapper: Database + 8 repos with old ReportStore method names.

    Lets existing test fixtures continue working with their original
    method call patterns (upsert_skill, get_learner_state, etc.) while
    delegating to the real per-domain repos on a shared Database.
    """

    def __init__(self, db_path):
        self.db = Database(db_path)
        self.reports = ReportRepository(self.db)
        self.messages = MessageRepository(self.db)
        self.notes = NoteRepository(self.db)
        self.skills = SkillRepository(self.db)
        self.learner_state = LearnerStateRepository(self.db)
        self.study_plans = StudyPlanRepository(self.db)
        self.pedagogy = PedagogicalPlanRepository(self.db)
        self.session_config = SessionConfigRepository(self.db)
        self.db_path = self.db.db_path
        self._lock = self.db.lock
        self._conn = self.db.conn

    def close(self):
        self.db.shutdown()

    # --- reports (old names) ---
    def save(self, r): return self.reports.save(r)
    def get(self, rid): return self.reports.get(rid)
    def search_reports(self, *a, **kw): return self.reports.search(*a, **kw)
    def search_reports_fts(self, *a, **kw): return self.reports.search_fts(*a, **kw)
    def delete_report(self, rid): return self.reports.delete(rid)

    # --- messages ---
    def save_messages(self, *a, **kw): return self.messages.save(*a, **kw)
    def append_message(self, *a, **kw): return self.messages.append(*a, **kw)
    def load_messages(self, *a, **kw): return self.messages.load(*a, **kw)
    def delete_messages_by_session(self, *a, **kw): return self.messages.delete_by_session(*a, **kw)

    # --- notes ---
    def create_note(self, *a, **kw): return self.notes.create(*a, **kw)
    def list_notes(self, *a, **kw): return self.notes.list_all(*a, **kw)
    def get_note(self, *a, **kw): return self.notes.get(*a, **kw)
    def rename_note(self, *a, **kw): return self.notes.rename(*a, **kw)
    def delete_note(self, *a, **kw): return self.notes.delete(*a, **kw)
    def save_note_content(self, *a, **kw): return self.notes.save_content(*a, **kw)
    def reorder_notes(self, *a, **kw): return self.notes.reorder(*a, **kw)

    # --- skills ---
    def upsert_skill(self, *a, **kw): return self.skills.upsert(*a, **kw)
    upsert = upsert_skill  # short name compat
    def get_skill(self, *a, **kw): return self.skills.get(*a, **kw)
    def list_skills(self, *a, **kw): return self.skills.list_active(*a, **kw)
    def supersede_skill(self, *a, **kw): return self.skills.supersede(*a, **kw)
    def bump_tree_version(self, *a, **kw): return self.skills.bump_tree_version(*a, **kw)
    def get_tree_version(self, *a, **kw): return self.skills.get_tree_version(*a, **kw)
    def get_tree(self, *a, **kw): return self.skills.get_tree(*a, **kw)
    def walk_topological(self, *a, **kw): return self.skills.walk_topological(*a, **kw)
    def search_skills_fts(self, *a, **kw): return self.skills.search_fts(*a, **kw)
    def add_edge(self, *a, **kw): return self.skills.add_edge(*a, **kw)
    def get_prerequisites(self, *a, **kw): return self.skills.get_prerequisites(*a, **kw)
    def start_build(self, *a, **kw): return self.skills.start_build(*a, **kw)
    def finish_build(self, *a, **kw): return self.skills.finish_build(*a, **kw)

    # --- learner_state ---
    def upsert_learner_state(self, *a, **kw): return self.learner_state.upsert(*a, **kw)
    def get_learner_state(self, *a, **kw): return self.learner_state.get(*a, **kw)
    def get_all_learner_states(self, *a, **kw): return self.learner_state.get_all(*a, **kw)
    get_all = get_all_learner_states  # short name

    # --- study_plans ---
    def create_plan(self, *a, **kw): return self.study_plans.create(*a, **kw)
    def supersede_plan(self, *a, **kw): return self.study_plans.supersede(*a, **kw)
    def get_active_plan(self, *a, **kw): return self.study_plans.get_active(*a, **kw)
    def add_plan_item(self, *a, **kw): return self.study_plans.add_item(*a, **kw)
    def replace_plan_items(self, *a, **kw): return self.study_plans.replace_items(*a, **kw)
    def update_plan_item(self, *a, **kw): return self.study_plans.update_item(*a, **kw)
    def get_plan_items(self, *a, **kw): return self.study_plans.get_items(*a, **kw)
    def get_plan_with_items(self, *a, **kw): return self.study_plans.get_with_items(*a, **kw)

    # --- pedagogy ---
    def save_pedagogical_plan(self, *a, **kw): return self.pedagogy.save(*a, **kw)
    def get_pedagogical_plan(self, *a, **kw): return self.pedagogy.get(*a, **kw)

    # --- session_config ---
    def save_session_config(self, *a, **kw): return self.session_config.save(*a, **kw)
    def load_session_config(self, *a, **kw): return self.session_config.load(*a, **kw)
    def delete_session_config(self, *a, **kw): return self.session_config.delete(*a, **kw)

    # --- short-name aliases (same as old ReportStore compat block) ---
    list_active = list_skills
    search_fts = search_skills_fts
    supersede = supersede_skill
    get_active = get_active_plan
    get_items = get_plan_items
    get_with_items = get_plan_with_items
    create = create_plan
    supersede_plan_alias = supersede_plan  # noqa
    replace_items = replace_plan_items
    add_item = add_plan_item
    update_item = update_plan_item
    list_all = list_notes
    rename = rename_note
    save_content = save_note_content
    reorder = reorder_notes
    save_msgs = save_messages  # noqa
    append = append_message
    load = load_messages
    delete_by_session = delete_messages_by_session
    save_ped_plan = save_pedagogical_plan
    get_ped_plan = get_pedagogical_plan
