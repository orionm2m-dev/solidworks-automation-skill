"""多页工程图布局的预检契约。"""
import pytest
from scripts.sw_drawing_book import DrawingBook


def book():
    out='C:/output/part-D2_A.SLDDRW'
    return {'output_path':out,'sheets':[{'name':'Sheet1','layout':{'output_path':out}}]}


def test_book_rejects_different_output_paths():
    data=book();data['sheets'][0]['layout']['output_path']='C:/output/other.SLDDRW'
    with pytest.raises(ValueError,match='share'):DrawingBook.model_validate(data)


def test_book_rejects_duplicate_sheet_names():
    data=book();data['sheets'].append(data['sheets'][0])
    with pytest.raises(ValueError,match='Duplicate'):DrawingBook.model_validate(data)


def test_book_rejects_unknown_field():
    data=book();data['overwrite']=True
    with pytest.raises(ValueError):DrawingBook.model_validate(data)


def test_book_accepts_ordered_unique_sheets():
    data=book();data['sheets'].append({'name':'Sheet2','layout':data['sheets'][0]['layout']})
    assert [s.name for s in DrawingBook.model_validate(data).sheets]==['Sheet1','Sheet2']
