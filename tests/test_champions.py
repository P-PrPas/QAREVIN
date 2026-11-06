import pytest

from qarevin.champions import ChampionBook, EvidenceRef
from qarevin.evidence import EvidenceStore
from qarevin.strategies import StrategySpec


def fixture_book(tmp_path):
    store=EvidenceStore(tmp_path/'research.sqlite')
    ids=[store.put('candidate',{'strategy':StrategySpec(family='trend',fast=fast).model_dump(),
                              'source_hash':'a'*64}) for fast in (50,40)]
    book=ChampionBook(store)
    book.freeze_baseline(ids[0])
    for index,candidate_id in enumerate(ids):
        store.put('job_result',{'manifest':{'candidate_id':candidate_id,'source_hash':'a'*64,'config_hash':'b'*64,
                                           'dataset_id':'c'*64,'kind':'walk_forward'},
                    'walk_forward':{'stitched_metrics':{'net_pnl':100+index},'split_hash':'d'*64,'bars_hash':'c'*64}},identity=str(index))
    refs=[EvidenceRef(kind='job_result',identifier=str(index),candidate_id=identifier) for index,identifier in enumerate(ids)]
    return store,book,ids,refs


def test_champion_is_frozen_and_accept_is_owner_scoped_not_deployment(tmp_path):
    store,book,ids,refs=fixture_book(tmp_path)
    with pytest.raises(ValueError,match='already frozen'):
        book.freeze_baseline(ids[1])
    nomination=book.nominate(*refs)
    assert book.current()['candidate_id']==ids[0]
    robust=store.put('robustness_result',{'eligible_for_holdout_request':True,'target':store.get('candidate',ids[1])['strategy'],
                                        'source_hash':'a'*64,'config_hash':'b'*64,'split_hash':'d'*64,'bars_hash':'c'*64})
    result=book.accept(nomination,robust,owner='owner',note='Owner reviewed matched fixed-artifact future evidence')
    assert not result['deployment_authorized'] and book.current()['version']==2
    assert len(store.list('champion_decision'))==2
    with pytest.raises(ValueError,match='stale'):
        book.accept(nomination,robust,owner='owner',note='Trying stale nomination again')
    assert store.verify_audit()


def test_mismatched_comparison_and_failed_robustness_rejected(tmp_path):
    store,book,ids,refs=fixture_book(tmp_path)
    failed=store.put('robustness_result',{'eligible_for_holdout_request':False})
    nomination=book.nominate(*refs)
    with pytest.raises(ValueError,match='passing'):
        book.accept(nomination,failed,owner='owner',note='Evidence is deliberately invalid')
    wrong=store.put('job_result',{'manifest':{'candidate_id':ids[1],'source_hash':'a'*64,'config_hash':'f'*64,
                                             'dataset_id':'c'*64},'scorecard':{'metrics':{}}})
    with pytest.raises(ValueError,match='matched'):
        book.nominate(refs[0],EvidenceRef(kind='job_result',identifier=wrong,candidate_id=ids[1]))
