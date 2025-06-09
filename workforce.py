# workforce_poco.py (already created)
from typing import List, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime
from bson import ObjectId

class TableRow(BaseModel):
    name: str
    required: bool
    allowed_values: Optional[List[str]] = None
    min_value: Optional[Union[float, str]] = None
    max_value: Optional[Union[float, str]] = None
    default_value: Optional[Union[float, str]] = None
    help_text: Optional[str] = None

class TableHeader(BaseModel):
    label: str
    headers: Optional[List["TableHeader"]] = None
    cell_type: str
    required: bool
    allowed_values: Optional[List[str]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    default_value: Optional[Union[float, str]] = None
    min_width: Optional[int] = None
    max_width: Optional[int] = None
    help_text: Optional[str] = None

class TableMetadata(BaseModel):
    headers: List[TableHeader]
    rows: List[TableRow]
    cell_type: str
    min_col_width: int
    max_col_width: int
    horizontal_scroll_threshold: int

class Question(BaseModel):
    question_id: str
    question: str
    type: str
    has_string_value: bool
    has_decimal_value: bool
    has_boolean_value: bool
    has_link: bool
    has_note: bool
    string_value_required: bool
    decimal_value_required: bool
    boolean_value_required: bool
    link_required: bool
    note_required: bool
    table_metadata: Optional[TableMetadata] = None

class QuestionCategory(BaseModel):
    id: str
    category_name: str
    questions: List[Question]

class Submodule(BaseModel):
    id: str
    submodule_name: str
    question_categories: List[QuestionCategory]

class WorkforceDocument(BaseModel):
    id: str
    company_id: str
    plant_id: str
    financial_year: str
    module_name: str
    submodules: List[Submodule]
    created_at: datetime
    updated_at: datetime
    _id: Optional[ObjectId] = None

    class Config:
        arbitrary_types_allowed = True