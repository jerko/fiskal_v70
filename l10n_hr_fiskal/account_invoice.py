# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Module: l10n_hr_fiskal
#    Author: Davor Bojkić
#    mail:   bole@dajmi5.com
#    Copyright (C) 2012- Daj Mi 5, 
#                  http://www.dajmi5.com
#    Contributions: Hrvoje ThePython - Free Code!
#                   Goran Kliska (AT) Slobodni Programi
#                    
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import fields, osv
from openerp.tools.translate import _
import uuid 

import pooler
from fiskal import *
import tools


class account_invoice(osv.Model):
    _inherit = "account.invoice"
    _columns = {
                'vrijeme_izdavanja': fields.datetime("Vrijeme", readonly=True),
                'fiskal_user_id'   : fields.many2one('res.users', 'Fiskalizirao', help='Fiskalizacija. Osoba koja je potvrdila racun'),
                'zki': fields.char('ZKI', size=64, readonly=True),
                'jir': fields.char('JIR',size=64 , readonly=True),
                'uredjaj_id':fields.many2one('fiskal.uredjaj', 'Naplatni uredjaj', help ="Naplatni uređaj na kojem se izdaje racun",
                                             readonly=True, states={'draft':[('readonly',False)]}),
                'fiskal_log_ids':fields.one2many('fiskal.log','invoice_id','Logovi poruka', help="Logovi poslanih poruka prema poreznoj upravi"),
                'nac_plac':fields.selection((
                                             ('G','GOTOVINA'),
                                             ('K','KARTICE'),
                                             ('C','CEKOVI'),
                                             ('T','TRANSAKCIJSKI RACUN'),
                                             ('O','OSTALO')
                                             ),
                                            'Nacin placanja', required=True, readonly=True, states={'draft':[('readonly',False)]})   
               }
    
    _defaults = {
                 'nac_plac':'G' # TODO : postaviti u bazi pitanje kaj da bude default!
                 }
    
    def onchange_journal_id(self, cr, uid, ids, journal_id=False, context=None):
        result = super(account_invoice,self).onchange_journal_id(cr, uid, ids, journal_id=journal_id, context=context)
        if journal_id:
            journal = self.pool.get('account.journal').browse(cr, uid, journal_id, context=context)
            prostor_id = journal.prostor_id and journal.prostor_id.id or False
            nac_plac = journal.nac_plac or False
            uredjaj_id = journal.fiskal_uredjaj_ids and journal.fiskal_uredjaj_ids[0].id or False
            result['value'].update({'nac_plac' : nac_plac,
                                    'uredjaj_id' : uredjaj_id,
                                   })
            result['domain']= result.get('domain',{})
            result['domain'].update({'uredjaj_id':[('prostor_id','=',prostor_id )]})
        return result
    
    def copy(self, cr, uid, id, default=None, context=None):
        default = default or {}
        default.update({
            'vrijeme_izdavanja':False,
            'fiskal_user_id':False,
            'zki':False,
            'jir': False,
            'fiskal_log_ids': False,
            #'prostor_id': False,
            #'nac_plac': False,
        })
        return super(account_invoice, self).copy(cr, uid, id, default, context)
       
    def prepare_fiskal_racun(self, cr, uid, id, context=None):
        """ Validate invoice, write min. data 
        """
        return True

    def button_fiscalize(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        for invoice in self.browse( cr, uid, ids, context):
            if not(invoice.jir):
                self.fiskaliziraj(cr, uid, invoice.id, context=context)
            elif len(invoice.jir)>30: #BOLE: JIR je 32 znaka
                raise osv.except_osv(_('FISKALIZIRANO!'), _('Nema potrebe ponavljati postupak fiskalizacije!.'))
            elif invoice.jir=='PONOVITI SLANJE!':
                raise osv.except_osv(_('Ovo nije doradjeno!'), _('Ukoliko vidite ovu poruku u problemu ste!.'))
                #TODO: uzeti ispravno vrijem od računa za ponovljeno slanje.. 
        
        
    def get_fiskal_taxes(self, cr, uid, invoice, a, context=None):
        res=[]
        
        def get_factory(val):
            fiskal_type = val.get('fiskal_type',False) 
            
            if fiskal_type=='pdv':      tns = {'tns': (a.racun.Pdv.Porez , 'tns:Porez')     , 'fields': ('Stopa' ,'Osnovica', 'Iznos') }  
            elif fiskal_type=='pnp':    tns = {'tns': (a.racun.Pnp.Porez , 'tns:Porez')     , 'fields': ('Stopa' ,'Osnovica', 'Iznos') }
            elif fiskal_type=='ostali': tns = {'tns': (a.racun.OstaliPor.Porez, 'tns:Porez'), 'fields': ('Naziv','Stopa' ,'Osnovica', 'Iznos') }
            elif fiskal_type=='naknade':tns = {'tns': (a.racun.Naknade, 'tns:Naknada'), 'fields': ('NazivN', 'IznosN') }

            elif fiskal_type=='oslobodenje':  tns = {'tns': (a.racun.IznosOslobPdv),   'value': 'Osnovica' }
            elif fiskal_type=='ne_podlijeze': tns = {'tns': (a.racun.IznosNePodlOpor), 'value': 'Osnovica' }
            elif fiskal_type=='marza':        tns = {'tns': (a.racun.IznosMarza),      'value': 'Osnovica' }
            else  :tns={}
            place = tns.get('tns',False)
            if not place:
                return False
            if len(place) > 1:      
                porez = a.client2.factory.create(place[1])
                place[0].append(porez)
            else:    
                porez = place[0]

            if tns.get('fields',False):
                for field in tns['fields']:
                    porez[field] = val[field]
                   
            if tns.get('value',False):
                tns['tns'][0] = val[field]

            return tns
        
        for tax in invoice.tax_line:
            if not tax.tax_code_id:
                continue #TODO special cases without tax code, or with base tax code without tax if found
            val={ 'tax_code': tax.tax_code_id.id,
                  'fiskal_type': tax.tax_code_id.fiskal_type,
                  'Naziv': tax.tax_code_id.name,
                  'Stopa': tax.tax_code_id.fiskal_percent,
                  'Osnovica': fiskal_num2str(tax.base_amount),
                  'Iznos': fiskal_num2str(tax.tax_amount),
                  'NazivN': tax.tax_code_id.name,
                 }
            res.append(val)
            #TODO group and sum by fiskal_type and Stopa hmmm then send 1 by one into factory... 
            get_factory(val)            
        return res
    
    def invoice_valid(self, cr, uid, invoice, context=None):
        if not invoice.journal_id.fiskal_active:
            raise osv.except_osv(_('Error'), _('Za ovaj dokument fiskalizacija nije aktivna!!'))
        if not invoice.fiskal_user_id.oib:
            raise osv.except_osv(_('Error'), _('Neispravan OIB korisnika!'))
        if not invoice.uredjaj_id.id:
            raise osv.except_osv(_('Error'), _('Nije odabran naplatni uredjaj / Dokument !'))
        return True

    def fiskaliziraj(self, cr, uid, id, context=None):
        """ Fiskalizira jedan izlazni racun
        """
        if context is None:
            context = {}
            
        prostor_obj= self.pool.get('fiskal.prostor')
        invoice= self.browse(cr, uid, [id])[0]
        
        #tko pokusava fiskalizirati?
        if not invoice.fiskal_user_id:
            self.write(cr, uid, [id], {'fiskal_user_id':uid})
            
        invoice= self.browse(cr, uid, [id])[0] #refresh

        #TODO - posebna funkcija za provjeru npr. invoice_fiskal_valid()
        
        self.invoice_valid(cr, uid, invoice)
        """
        if not invoice.fiskal_user_id.oib:
            raise osv.except_osv(_('Error'), _('Neispravan OIB korisnika!'))
        if not invoice.uredjaj_id.id:
            raise osv.except_osv(_('Error'), _('Nije odabran naplatni uredjaj / Dokument !'))
        """
        wsdl, key, cert = prostor_obj.get_fiskal_data(cr, uid, company_id=invoice.company_id.id)
        if not wsdl:
            return False
        a = Fiskalizacija('racun', wsdl, key, cert, cr, uid, oe_obj = invoice)
        
        start_time=a.time_formated()
        a.t = start_time['datum'] 
        a.zaglavlje.DatumVrijeme = start_time['datum_vrijeme'] #TODO UTC -> Europe/Zagreb 
        a.zaglavlje.IdPoruke = str(uuid.uuid4())
        
        dat_vrijeme = invoice.vrijeme_izdavanja
        if not dat_vrijeme:
            dat_vrijeme = start_time['datum_vrijeme']
            self.write(cr, uid, [id], {'vrijeme_izdavanja': start_time['time_stamp'].strftime(tools.DEFAULT_SERVER_DATETIME_FORMAT) })
        
        if not invoice.company_id.fina_certifikat_id:
            raise osv.except_osv(_('No certificate!'), _('No valid certificate found for fiscalization usage, Please provide one.'))
            pass #TODO Error
        if invoice.company_id.fina_certifikat_id.cert_type == 'fina_prod':
            a.racun.Oib = invoice.company_id.partner_id.vat[2:]  # pravi OIB company
        elif invoice.company_id.fina_certifikat_id.cert_type == 'fina_demo':
            a.racun.Oib = invoice.uredjaj_id.prostor_id.spec[2:]  #OIB IT firme 
        else:
            pass #TODO Error
         
        a.racun.DatVrijeme = dat_vrijeme #invoice.vrijeme_izdavanja
        a.racun.OznSlijed = invoice.uredjaj_id.prostor_id.sljed_racuna #'P' ## sljed_racuna

        #dijelovi broja racuna
        BrojOznRac, OznPosPr, OznNapUr = invoice.number.rsplit('/',2)
        BrOznRac = ''
        for b in ''.join([x for x in BrojOznRac[::-1]]): #reverse
            if b.isdigit() :BrOznRac += b                #
            else: break                                  #break on 1. non digit
        BrOznRac = BrOznRac[::-1].lstrip('0')    #reverse again and strip leading zeros

        a.racun.BrRac.BrOznRac = BrOznRac
        a.racun.BrRac.OznPosPr = OznPosPr
        a.racun.BrRac.OznNapUr = OznNapUr
        
        a.racun.USustPdv = invoice.uredjaj_id.prostor_id.sustav_pdv and "true" or "false"
        if invoice.uredjaj_id.prostor_id.sustav_pdv:
            self.get_fiskal_taxes(cr, uid, invoice, a, context=context)
        
        a.racun.IznosUkupno = fiskal_num2str(invoice.amount_total)
        
        a.racun.NacinPlac = invoice.nac_plac
        a.racun.OibOper = invoice.fiskal_user_id.oib[2:]  #"57699704120"
        
        if not invoice.zki:
            a.racun.NakDost = "false"  ##TODO rutina koja provjerava jel prvi puta ili ponovljeno sranje!
            a.izracunaj_zastitni_kod() #start_time['datum_racun'])
            self.write(cr,uid,id,{'zki':a.racun.ZastKod})
        else :
            a.racun.NakDost = "true"
            a.racun.ZastKod = invoice.zki
        
        fiskaliziran = a.posalji_racun()
        
        if fiskaliziran:
            jir = a.poruka_odgovor[1].Jir
            self.write(cr,uid,id,{'jir':jir})
        else:
            self.write(cr,uid,id,{'jir':'PONOVITI SLANJE!'})
            
            

    def refund(self, cr, uid, ids, date=None, period_id=None, description=None, journal_id=None):
        #Where is the context, per invoice method?
        #This approach is slow, updating after creating, but maybe better than copy-paste whole method
        #FUBAR 
        res = super(account_invoice, self).refund(cr, uid, ids, date=date, period_id=period_id, description=description, journal_id=journal_id)
        source_invoice = self.browse(cr, uid, ids)[0] # what if we get more then one?
        self.write(cr, uid, res,
                   {'uredjaj_id': source_invoice.uredjaj_id and source_invoice.uredjaj_id.id or False,
                    })
            
                        
        return res
            
            