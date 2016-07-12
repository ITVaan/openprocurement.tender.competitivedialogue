# -*- coding: utf-8 -*-
from datetime import timedelta
from schematics.types import StringType
from schematics.exceptions import ValidationError
from zope.interface import implementer
from pyramid.security import Allow
from schematics.types.compound import ModelType
from schematics.types.serializable import serializable
from openprocurement.api.models import ITender, Identifier, Model, Value
from openprocurement.api.utils import calculate_business_date, get_now
from openprocurement.tender.openua.models import SifterListType, Item as BaseItem
from openprocurement.tender.openeu.models import (Tender as TenderEU, Administrator_bid_role, view_bid_role,
                                                  pre_qualifications_role, Bid as BidEU, ConfidentialDocument,
                                                  edit_role_eu, auction_patch_role, auction_view_role,
                                                  auction_post_role, QUESTIONS_STAND_STILL, ENQUIRY_STAND_STILL_TIME,
                                                  PeriodStartEndRequired, EnquiryPeriod, Lot as BaseLot,
                                                  validate_lots_uniq, embedded_lot_role, default_lot_role)
from openprocurement.api.models import (
    plain_role, create_role, edit_role, view_role, listing_role,
    enquiries_role, validate_cpv_group, validate_items_uniq,
    chronograph_role, chronograph_view_role, ProcuringEntity as BaseProcuringEntity,
    Administrator_role, schematics_default_role,
    schematics_embedded_role, ListType, BooleanType
)
from schematics.transforms import whitelist, blacklist

# constants for procurementMethodtype
CD_UA_TYPE = "competitiveDialogueUA"
CD_EU_TYPE = "competitiveDialogueEU"
STAGE_2_EU_TYPE = "competitiveDialogueEU.stage2"
STAGE_2_UA_TYPE = "competitiveDialogueUA.stage2"

STAGE2_STATUS = 'draft.stage2'

edit_role_ua = edit_role + blacklist('enquiryPeriod', 'status')
edit_stage2_pending = whitelist('status')
edit_stage2_waiting = whitelist('status', 'stage2TenderID')
hide_minimal_step = blacklist('minimalStep')

roles = {
    'plain': plain_role + hide_minimal_step,
    'create': create_role + hide_minimal_step,
    'view': view_role + hide_minimal_step,
    'listing': listing_role,
    'active.pre-qualification': pre_qualifications_role + hide_minimal_step,
    'active.pre-qualification.stand-still': pre_qualifications_role + hide_minimal_step,
    'active.stage2.pending': enquiries_role + hide_minimal_step,
    'active.stage2.waiting': pre_qualifications_role + hide_minimal_step,
    'edit_active.stage2.pending': whitelist('status'),
    'draft': enquiries_role + hide_minimal_step,
    'active.tendering': enquiries_role + hide_minimal_step,
    'complete': view_role + hide_minimal_step,
    'unsuccessful': view_role + hide_minimal_step,
    'cancelled': view_role + hide_minimal_step,
    'chronograph': chronograph_role,
    'chronograph_view': chronograph_view_role,
    'Administrator': Administrator_role,
    'default': schematics_default_role + hide_minimal_step,
    'contracting': whitelist('doc_id', 'owner'),
    'competitive_dialogue': edit_stage2_waiting
}


class Document(ConfidentialDocument):
    """ Document model with new feature as Description of the decision to purchase """

    class Options:
        roles = {
            'edit': blacklist('id', 'url', 'datePublished', 'dateModified', ''),
            'embedded': schematics_embedded_role,
            'view': (blacklist('revisions') + schematics_default_role),
            'restricted_view': (blacklist('revisions', 'url') + schematics_default_role),
            'revisions': whitelist('url', 'dateModified'),
        }

    isDescriptionDecision = BooleanType(default=False)

    def validate_confidentialityRationale(self, data, val):
        if data['confidentiality'] != 'public' and not data['isDescriptionDecision']:
            if not val:
                raise ValidationError(u"confidentialityRationale is required")
            elif len(val) < 30:
                raise ValidationError(u"confidentialityRationale should contain at least 30 characters")


class Bid(BidEU):
    class Options:
        roles = {
            'Administrator': Administrator_bid_role,
            'embedded': view_bid_role,
            'view': view_bid_role,
            'create': whitelist('value', 'tenderers', 'parameters', 'lotValues',
                                'status', 'selfQualified', 'selfEligible', 'subcontractingDetails'),
            'edit': whitelist('value', 'tenderers', 'parameters', 'lotValues', 'status', 'subcontractingDetails'),
            'active.enquiries': whitelist(),
            'active.tendering': whitelist(),
            'active.pre-qualification': whitelist('id', 'status', 'documents', 'tenderers'),
            'active.pre-qualification.stand-still': whitelist('id', 'status', 'documents', 'tenderers'),
            'active.auction': whitelist('id', 'status', 'documents', 'tenderers'),
            'active.stage2.pending': whitelist('id', 'status', 'documents', 'tenderers'),
            'active.qualification': view_bid_role,
            'complete': view_bid_role,
            'unsuccessful': view_bid_role,
            'bid.unsuccessful': whitelist('id', 'status', 'tenderers', 'parameters',
                                          'selfQualified', 'selfEligible', 'subcontractingDetails'),
            'cancelled': view_bid_role,
            'invalid': whitelist('id', 'status'),
            'deleted': whitelist('id', 'status'),
        }

    documents = ListType(ModelType(Document), default=list())

lot_roles = {
    'create': whitelist('id', 'title', 'title_en', 'title_ru', 'description', 'description_en', 'description_ru', 'value', 'guarantee'),
    'edit': whitelist('title', 'title_en', 'title_ru', 'description', 'description_en', 'description_ru', 'value', 'guarantee'),
    'embedded': embedded_lot_role,
    'view': default_lot_role + blacklist('minimalStep'),
    'default': default_lot_role + blacklist('minimalStep'),
    'chronograph': whitelist('id', 'auctionPeriod'),
    'chronograph_view': whitelist('id', 'auctionPeriod', 'numberOfBids', 'status'),
}


class Lot(BaseLot):

    minimalStep = ModelType(Value, required=False)

    def validate_minimalStep(self, data, value):
        if data.get('minimalStep'):
            raise ValidationError(u"Rogue field")

    @serializable(serialized_name="minimalStep", type=ModelType(Value), serialize_when_none=False)
    def lot_minimalStep(self):
        return None

    class Options:
        roles = lot_roles.copy()


@implementer(ITender)
class Tender(TenderEU):
    procurementMethodType = StringType(default=CD_EU_TYPE)
    status = StringType(choices=['draft', 'active.tendering', 'active.pre-qualification',
                                 'active.pre-qualification.stand-still', 'active.stage2.pending',
                                 'active.stage2.waiting', 'complete', 'cancelled', 'unsuccessful'],
                        default='active.tendering')
    # A list of all the companies who entered submissions for the tender.
    bids = SifterListType(ModelType(Bid), default=list(),
                          filter_by='status', filter_in_values=['invalid', 'deleted'])
    TenderID = StringType(required=False)
    stage2TenderID = StringType(required=False)
    minimalStep = ModelType(Value, required=False, serialize_when_none=False)
    lots = ListType(ModelType(Lot), default=list(), validators=[validate_lots_uniq])

    def validate_minimalStep(self, data, data_from_request):
        if data.get('minimalStep'):
            raise ValidationError(u"Rogue field")

    @serializable(serialized_name="minimalStep", type=ModelType(Value), serialize_when_none = False)
    def tender_minimalStep(self):
        return None

    class Options:
        roles = roles.copy()

    def get_role(self):
        root = self.__parent__
        request = root.request
        if request.authenticated_role == 'Administrator':
            role = 'Administrator'
        elif request.authenticated_role == 'chronograph':
            role = 'chronograph'
        elif request.authenticated_role == 'competitive_dialogue':
            role = 'competitive_dialogue'
        else:
            role = 'edit_{}'.format(request.context.status)
        return role

    def __acl__(self):
        acl = [
            (Allow, '{}_{}'.format(i.owner, i.owner_token), 'create_qualification_complaint')
            for i in self.bids
            if i.status in ['active', 'unsuccessful']
            ]
        acl.extend(
            [(Allow, '{}_{}'.format(i.owner, i.owner_token), 'create_award_complaint')
             for i in self.bids
             if i.status == 'active'
             ])
        acl.extend([
            (Allow, '{}_{}'.format(self.owner, self.owner_token), 'edit_tender'),
            (Allow, '{}_{}'.format(self.owner, self.owner_token), 'upload_tender_documents'),
            (Allow, '{}_{}'.format(self.owner, self.owner_token), 'edit_complaint'),
            (Allow, 'g:competitive_dialogue', 'extract_credentials'),
            (Allow, 'g:competitive_dialogue', 'edit_tender'),
        ])
        return acl


CompetitiveDialogEU = Tender


class LotId(Model):
    id = StringType()


class Firms(Model):
    identifier = ModelType(Identifier, required=True)
    name = StringType(required=True)
    lots = ListType(ModelType(LotId), default=list())


@implementer(ITender)
class Tender(CompetitiveDialogEU):
    procurementMethodType = StringType(default=CD_UA_TYPE)
    title_en = StringType()
    items = ListType(ModelType(BaseItem), required=True, min_size=1,
                     validators=[validate_cpv_group, validate_items_uniq])
    procuringEntity = ModelType(BaseProcuringEntity, required=True)
    stage2TenderID = StringType(required=False)


CompetitiveDialogUA = Tender


# stage 2 models

class Lot(BaseLot):

    minimalStep = ModelType(Value, required=True, default=Value({"amount": 0}))


LotStage2 = Lot

hide_dialogue_token = blacklist('dialogue_token')
close_edit_technical_fields = blacklist('dialogue_token', 'shortlistedFirms', 'dialogueID')


stage_2_roles = {
    'plain': plain_role,
    'create': (blacklist('owner_token', 'tenderPeriod', '_attachments', 'revisions', 'dateModified', 'doc_id', 'tenderID', 'bids', 'documents', 'awards', 'questions', 'complaints', 'auctionUrl', 'status', 'auctionPeriod', 'awardPeriod', 'awardCriteria', 'submissionMethod', 'cancellations') + schematics_embedded_role),
    'edit': edit_role_eu + close_edit_technical_fields,
    'edit_draft': edit_role_eu + close_edit_technical_fields,
    'edit_active.tendering': edit_role_eu + close_edit_technical_fields,
    'edit_active.pre-qualification': whitelist('status'),
    'edit_active.pre-qualification.stand-still': whitelist(),
    'edit_active.auction': whitelist(),
    'edit_active.qualification': whitelist(),
    'edit_active.awarded': whitelist(),
    'edit_complete': whitelist(),
    'edit_unsuccessful': whitelist(),
    'edit_cancelled': whitelist(),
    'view': view_role + hide_dialogue_token,
    'listing': listing_role,
    'auction_view': auction_view_role,
    'auction_post': auction_post_role,
    'auction_patch': auction_patch_role,
    'draft': enquiries_role + blacklist('dialogue_token', 'shortlistedFirms'),
    'draft.stage2': enquiries_role + hide_dialogue_token,
    'active.tendering': enquiries_role + hide_dialogue_token,
    'active.pre-qualification': pre_qualifications_role + hide_dialogue_token,
    'active.pre-qualification.stand-still': pre_qualifications_role + hide_dialogue_token,
    'active.auction': pre_qualifications_role + hide_dialogue_token,
    'active.qualification': view_role + hide_dialogue_token,
    'active.awarded': view_role + hide_dialogue_token,
    'complete': view_role + hide_dialogue_token,
    'unsuccessful': view_role + hide_dialogue_token,
    'cancelled': view_role + hide_dialogue_token,
    'chronograph': chronograph_role,
    'chronograph_view': chronograph_view_role,
    'Administrator': Administrator_role,
    'default': schematics_default_role,
    'contracting': whitelist('doc_id', 'owner'),
    'competitive_dialogue': edit_stage2_waiting
}


def init_PeriodStartEndRequired():
    return PeriodStartEndRequired({"startDate": get_now(),
                                   "endDate": calculate_business_date(get_now(), timedelta(days=30))})

@implementer(ITender)
class Tender(TenderEU):
    procurementMethodType = StringType(default=STAGE_2_EU_TYPE)
    dialogue_token = StringType(required=True)
    dialogueID = StringType()
    shortlistedFirms = ListType(ModelType(Firms), required=True)
    tenderPeriod = ModelType(PeriodStartEndRequired, required=False,
                             default=init_PeriodStartEndRequired)
    minimalStep = ModelType(Value, required=True, default=Value({'amount': 0}))
    lots = ListType(ModelType(LotStage2), default=list())
    status = StringType(
        choices=['draft', 'active.tendering', 'active.pre-qualification', 'active.pre-qualification.stand-still',
                 'active.auction', 'active.qualification', 'active.awarded', 'complete', 'cancelled',
                 'unsuccessful', STAGE2_STATUS],
        default='active.tendering')

    create_accreditation = 'c'

    class Options:
        roles = stage_2_roles.copy()

    def __acl__(self):
        acl = [
            (Allow, '{}_{}'.format(self.owner, self.dialogue_token), 'generate_credentials')
        ]
        acl.extend([
            (Allow, '{}_{}'.format(i.owner, i.owner_token), 'create_qualification_complaint')
            for i in self.bids
            if i.status in ['active', 'unsuccessful']
            ])
        acl.extend([
            (Allow, '{}_{}'.format(i.owner, i.owner_token), 'create_award_complaint')
            for i in self.bids
            if i.status == 'active'
            ])
        acl.extend([
            (Allow, '{}_{}'.format(self.owner, self.owner_token), 'edit_tender'),
            (Allow, '{}_{}'.format(self.owner, self.owner_token), 'upload_tender_documents'),
            (Allow, '{}_{}'.format(self.owner, self.owner_token), 'edit_complaint'),
            (Allow, 'g:competitive_dialogue', 'edit_tender')
        ])
        return acl

    def initialize(self):
        self.tenderPeriod = PeriodStartEndRequired(
            dict(startDate=get_now(), endDate=calculate_business_date(get_now(), timedelta(days=30), self)))
        endDate = calculate_business_date(self.tenderPeriod.endDate, -QUESTIONS_STAND_STILL, self)
        self.enquiryPeriod = EnquiryPeriod(dict(startDate=self.tenderPeriod.startDate,
                                                endDate=endDate,
                                                invalidationDate=self.enquiryPeriod and self.enquiryPeriod.invalidationDate,
                                                clarificationsUntil=calculate_business_date(endDate,
                                                                                            ENQUIRY_STAND_STILL_TIME,
                                                                                            self, True)))


TenderStage2EU = Tender


@implementer(ITender)
class Tender(TenderStage2EU):
    procurementMethodType = StringType(default=STAGE_2_UA_TYPE)
    title_en = StringType()

TenderStage2UA = Tender
