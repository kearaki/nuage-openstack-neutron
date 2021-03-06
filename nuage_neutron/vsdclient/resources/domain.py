# Copyright 2016 NOKIA
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging
import netaddr

from nuage_neutron.vsdclient.common.cms_id_helper import get_vsd_external_id
from nuage_neutron.vsdclient.common.cms_id_helper import strip_cms_id
from nuage_neutron.vsdclient.common import constants
from nuage_neutron.vsdclient.common import helper
from nuage_neutron.vsdclient.common import nuagelib
from nuage_neutron.vsdclient.common import pnet_helper
from nuage_neutron.vsdclient.resources import dhcpoptions
from nuage_neutron.vsdclient import restproxy

VSD_RESP_OBJ = constants.VSD_RESP_OBJ
TEMPLATE_ISOLATED_ZONE = constants.TEMPLATE_ISOLATED_ZONE
TEMPLATE_SHARED_ZONE = constants.TEMPLATE_SHARED_ZONE

LOG = logging.getLogger(__name__)


class NuageDomain(object):
    def __init__(self, restproxy_serv, policygroups):
        self.restproxy = restproxy_serv
        self.domainsubnet = NuageDomainSubnet(restproxy_serv,
                                              policygroups)

    def _create_nuage_def_l3domain_acl(self, id, neutron_router_id):
        nuageibacl_id = self._create_nuage_l3dom_ingress_tmplt(
            id,
            neutron_router_id)
        nuageobacl_id = self._create_nuage_l3dom_egress_tmplt(
            id,
            neutron_router_id)
        return nuageibacl_id, nuageobacl_id

    def _create_nuage_l3dom_ingress_tmplt(self, id, neutron_router_id):
        req_params = {
            'parent_id': id,
            'name': id,
            'externalID': get_vsd_external_id(neutron_router_id)
        }
        nuageibacl = nuagelib.NuageInboundACL(create_params=req_params)
        response = self.restproxy.rest_call('POST',
                                            nuageibacl.post_resource_l3(),
                                            nuageibacl.post_data_default_l3())
        if not nuageibacl.validate(response):
            raise restproxy.RESTProxyError(nuageibacl.error_msg)
        return nuageibacl.get_iacl_id(response)

    def _create_nuage_l3dom_egress_tmplt(self, id, neutron_router_id):
        req_params = {
            'parent_id': id,
            'name': id,
            'externalID': get_vsd_external_id(neutron_router_id)
        }
        nuageobacl = nuagelib.NuageOutboundACL(create_params=req_params)
        response = self.restproxy.rest_call('POST',
                                            nuageobacl.post_resource_l3(),
                                            nuageobacl.post_data_default_l3())
        if not nuageobacl.validate(response):
            raise restproxy.RESTProxyError(nuageobacl.error_msg)
        return nuageobacl.get_oacl_id(response)

    def _nuage_pat_enabled_or_disabled(self, router, params):
        nuage_pat = 'DISABLED'
        if not params:
            return nuage_pat
        ext_gw_info = router.get('external_gateway_info')
        if ext_gw_info:
            if params['nuage_pat'] == constants.NUAGE_PAT_DEF_ENABLED:
                enable_snat = ext_gw_info.get('enable_snat', True)
                if enable_snat:
                    nuage_pat = 'ENABLED'
            elif params['nuage_pat'] == constants.NUAGE_PAT_DEF_DISABLED:
                enable_snat = ext_gw_info.get('enable_snat', False)
                if enable_snat:
                    nuage_pat = 'ENABLED'
        return nuage_pat

    def get_router_by_external(self, ext_id):
        params = {
            'externalID': get_vsd_external_id(ext_id)
        }

        nuagerouter = nuagelib.NuageL3Domain(create_params=params)
        response = self.restproxy.rest_call(
            'GET', nuagerouter.get_resource_with_ext_id(), '',
            extra_headers=nuagerouter.extra_headers_get())
        if not nuagerouter.validate(response):
            raise restproxy.RESTProxyError(nuagerouter.error_msg)
        if response[3]:
            return nuagerouter.get_response_obj(response)
        else:
            return None

    def _create_nuage_def_l3domain_adv_fwd_template(self, l3dom_id,
                                                    neutron_router_id):
        nuageadvfwdtmplt = nuagelib.NuageInAdvFwdTemplate()
        response = self.restproxy.rest_call(
            'POST',
            nuageadvfwdtmplt.post_resource_l3(l3dom_id),
            nuageadvfwdtmplt.post_data_default_l3(
                l3dom_id,
                get_vsd_external_id(neutron_router_id)))
        if not nuageadvfwdtmplt.validate(response):
            raise restproxy.RESTProxyError(nuageadvfwdtmplt.error_msg)
        return nuageadvfwdtmplt.get_response_objid(response)

    def get_routers_by_netpart(self, netpart_id):
        nuagel3dom = nuagelib.NuageL3Domain({'net_partition_id': netpart_id})
        response = self.restproxy.rest_call(
            'GET', nuagel3dom.get_all_resources_in_ent(), '')
        if not nuagel3dom.validate(response):
            raise restproxy.RESTProxyError(nuagel3dom.error_msg)
        res = []
        for l3dom in nuagel3dom.get_response_objlist(response):
            np_dict = dict()
            np_dict['domain_name'] = l3dom['name']
            np_dict['domain_id'] = l3dom['ID']
            res.append(np_dict)
        return res

    def create_router(self, neutron_router, router, params):
        net_partition = params['net_partition']
        req_params = {
            'net_partition_id': net_partition['id'],
            'name': neutron_router['id'],
            'templateID': net_partition['l3dom_tmplt_id'],
            'externalID': get_vsd_external_id(neutron_router['id'])
        }
        if router['nuage_router_template']:
            req_params['templateID'] = router['nuage_router_template']

        extra_params = {
            'description': neutron_router['name']
        }
        if 'rd' in router.keys() and router['rd']:
            extra_params['routeDistinguisher'] = router['rd']
        if 'rt' in router.keys() and router['rt']:
            extra_params['routeTarget'] = router['rt']
        if router.get('tunnel_type'):
            neutron_tunnel_type = router['tunnel_type']
            vsd_types = constants.VSD_TUNNEL_TYPES
            extra_params['tunnelType'] = vsd_types[neutron_tunnel_type]
        if 'ecmp_count' in router:
            extra_params['ECMPCount'] = router.get('ecmp_count')
        if ('nuage_backhaul_vnid' in router.keys() and
                router['nuage_backhaul_vnid']):
            extra_params['backHaulVNID'] = router['nuage_backhaul_vnid']
        if ('nuage_backhaul_rd' in router.keys() and
                router['nuage_backhaul_rd']):
            extra_params['backHaulRouteDistinguisher'] = (
                router['nuage_backhaul_rd'])
        if ('nuage_backhaul_rt' in router.keys() and
                router['nuage_backhaul_rt']):
            extra_params['backHaulRouteTarget'] = router['nuage_backhaul_rt']

        # PATEnabled
        extra_params['PATEnabled'] = self._nuage_pat_enabled_or_disabled(
            router, params)
        extra_params['underlayEnabled'] = extra_params['PATEnabled']

        router_dict = {}
        nuagel3domain = nuagelib.NuageL3Domain(create_params=req_params,
                                               extra_params=extra_params)

        response = self.restproxy.rest_call(
            'POST', nuagel3domain.post_resource(), nuagel3domain.post_data())
        if not nuagel3domain.validate(response):
            if not nuagel3domain.resource_exists(response):
                code = nuagel3domain.get_error_code(response)
                raise restproxy.RESTProxyError(nuagel3domain.error_msg,
                                               error_code=code)
            response = self.restproxy.rest_call(
                'GET', nuagel3domain.get_resource_with_ext_id(), '',
                extra_headers=nuagel3domain.extra_headers_get())
            if not nuagel3domain.get_validate(response):
                raise restproxy.RESTProxyError(nuagel3domain.error_msg)

        nuage_domain_id = nuagel3domain.get_domainid(response)
        external_id = nuagel3domain.get_response_externalid(response)
        parent_id = nuagel3domain.get_response_parentid(response)
        router_dict['nuage_external_id'] = strip_cms_id(external_id)
        router_dict['nuage_parent_id'] = parent_id
        router_dict['nuage_domain_id'] = nuage_domain_id
        router_dict['rt'] = nuagel3domain.get_domain_rt(response)
        router_dict['rd'] = nuagel3domain.get_domain_rd(response)
        router_dict['ecmp_count'] = nuagel3domain.get_domain_ecmp_count(
            response)
        router_dict['tunnel_type'] = nuagel3domain.get_domain_tunnel_type(
            response)
        router_dict['nuage_backhaul_vnid'] = (
            nuagel3domain.get_domain_backhaul_vnid(response))
        router_dict['nuage_backhaul_rd'] = (
            nuagel3domain.get_domain_backhaul_rd(response))
        router_dict['nuage_backhaul_rt'] = (
            nuagel3domain.get_domain_backhaul_rt(response))

        req_params = {
            'domain_id': nuage_domain_id
        }
        nuage_zone = nuagelib.NuageZone(req_params)
        response = self.restproxy.rest_call('GET', nuage_zone.list_resource(),
                                            '')
        if not nuage_zone.validate(response):
            self.delete_router(nuage_domain_id)
            raise restproxy.RESTProxyError(nuage_zone.error_msg)

        isolated_id = None
        shared_id = None

        if router['nuage_router_template'] is not None:
            for zone in nuage_zone.zone_list(response):
                if (zone['name'] == TEMPLATE_ISOLATED_ZONE and
                        not zone['publicZone']):
                    isolated_id = zone['ID']
                elif (zone['name'] == TEMPLATE_SHARED_ZONE and
                      not zone['publicZone']):
                    shared_id = zone['ID']
                external_id_params = {
                    'zone_id': zone['ID']
                }
                external_id_zone = nuagelib.NuageZone(
                    create_params=external_id_params)
                helper.set_external_id_only(
                    self.restproxy,
                    resource=external_id_zone.get_resource(),
                    id=neutron_router['id'])
            if not isolated_id or not shared_id:
                msg = ("Mandatory zones %s or %s do not exist in VSD" % (
                    TEMPLATE_ISOLATED_ZONE, TEMPLATE_SHARED_ZONE))
                self.delete_router(nuage_domain_id)
                raise restproxy.RESTProxyError(msg)
            router_dict['nuage_def_zone_id'] = isolated_id
            router_dict['nuage_shared_zone_id'] = shared_id
            self._make_nuage_zone_shared(net_partition['id'], shared_id,
                                         params['tenant_id'])
        elif net_partition.get('isolated_zone', None):
            for zone in nuage_zone.zone_list(response):
                if zone['name'] == net_partition['isolated_zone']:
                    isolated_id = zone['ID']
                if zone['name'] == net_partition['shared_zone']:
                    shared_id = zone['ID']
                external_id_params = {
                    'zone_id': zone['ID']
                }
                external_id_zone = nuagelib.NuageZone(
                    create_params=external_id_params)
                helper.set_external_id_only(
                    self.restproxy,
                    resource=external_id_zone.get_resource(),
                    id=neutron_router['id'])
            if not isolated_id or not shared_id:
                msg = "Default zones do not exist in VSD"
                self.delete_router(nuage_domain_id)
                raise restproxy.RESTProxyError(msg)

            router_dict['nuage_def_zone_id'] = isolated_id
            router_dict['nuage_shared_zone_id'] = shared_id
            # TODO(Ronak) - Handle exception here
            self._make_nuage_zone_shared(net_partition['id'], shared_id,
                                         params['tenant_id'])
        # TODO(Divya) - the following else block seems redudant, see if can
        # be removed
        else:
            router_dict['nuage_def_zone_id'] = nuage_zone.get_isolated_zone_id(
                response)
            external_id_params = {
                'zone_id': router_dict['nuage_def_zone_id']
            }
            external_id_zone = nuagelib.NuageZone(
                create_params=external_id_params)
            helper.set_external_id_only(
                self.restproxy,
                resource=external_id_zone.get_resource(),
                id=neutron_router['id'])
            shared_id = nuage_zone.get_shared_zone_id(response)
            external_id_zone['zone_id'] = shared_id
            external_id_zone = nuagelib.NuageZone(
                create_params=external_id_params)
            helper.set_external_id_only(
                self.restproxy,
                resource=external_id_zone.get_resource(),
                id=neutron_router['id'])
            self._make_nuage_zone_shared(net_partition['id'], shared_id,
                                         params['tenant_id'])

        nuage_userid, nuage_groupid = \
            helper.create_usergroup(self.restproxy, params['tenant_id'],
                                    params['net_partition']['id'])
        router_dict['nuage_userid'] = nuage_userid
        router_dict['nuage_groupid'] = nuage_groupid

        self._attach_nuage_group_to_zone(nuage_groupid,
                                         router_dict['nuage_def_zone_id'],
                                         params['tenant_id'])
        iacl_id, oacl_id = self._create_nuage_def_l3domain_acl(
            nuage_domain_id, neutron_router['id'])
        router_dict['iacl_id'] = iacl_id
        router_dict['oacl_id'] = oacl_id
        self._create_nuage_def_l3domain_adv_fwd_template(nuage_domain_id,
                                                         neutron_router['id'])
        return router_dict

    def update_router(self, nuage_domain_id, router, params):
        nuage_pat = self._nuage_pat_enabled_or_disabled(router, params)
        tunnel_types = constants.VSD_TUNNEL_TYPES
        update_dict = {
            'name': router['id'],
            'description': router['name'],
            'PATEnabled': nuage_pat,
            'underlayEnabled': nuage_pat,
            'routeDistinguisher': router.get('rd'),
            'routeTarget': router.get('rt'),
            'tunnelType': tunnel_types.get(router.get('tunnel_type'),
                                           router.get('tunnel_type')),
            'ECMPCount': router.get('ecmp_count'),
            'backHaulVNID': router.get('nuage_backhaul_vnid'),
            'backHaulRouteDistinguisher': router.get('nuage_backhaul_rd'),
            'backHaulRouteTarget': router.get('nuage_backhaul_rt')
        }

        nuagel3domain = nuagelib.NuageL3Domain()
        self.restproxy.put(nuagel3domain.delete_resource(nuage_domain_id),
                           update_dict)

    def _make_nuage_zone_shared(self, nuage_netpartid, nuage_zoneid,
                                neutron_tenant_id):
        params = {
            'net_partition_id': nuage_netpartid
        }
        nuagegroup = nuagelib.NuageGroup(create_params=params)
        response = self.restproxy.rest_call(
            'GET',
            nuagegroup.list_resource(), '',
            nuagegroup.extra_headers_get_for_everybody())
        if not nuagegroup.validate(response):
            raise restproxy.RESTProxyError(nuagegroup.error_msg)

        nuage_all_groupid = nuagegroup.get_groupid(response)
        self._attach_nuage_group_to_zone(nuage_all_groupid,
                                         nuage_zoneid,
                                         neutron_tenant_id)

    def delete_router(self, id):
        nuagel3domain = nuagelib.NuageL3Domain()
        self.restproxy.delete(nuagel3domain.delete_resource(id))

    def validate_zone_create(self, l3dom_id,
                             l3isolated, l3shared):
        params = {
            'l3domain_id': l3dom_id
        }
        nuagezonetemplate = nuagelib.NuageZoneTemplate(create_params=params)
        response = self.restproxy.rest_call(
            'GET', nuagezonetemplate.list_resource(), '')
        if not nuagezonetemplate.validate(response):
            raise restproxy.RESTProxyError(nuagezonetemplate.error_msg)
        isolated_match = False
        shared_match = False
        zone_tlist = nuagezonetemplate.zonetemplate_list(response)
        for zone in zone_tlist:
            if zone['name'] == l3isolated:
                isolated_match = True
            if zone['name'] == l3shared:
                shared_match = True
        return (shared_match, isolated_match)

    def delete_nuage_staticroute(self, params):
        static_route = self.get_nuage_static_route(params)
        if static_route:
            nuage_staticroute = nuagelib.NuageStaticRoute()
            self.restproxy.rest_call(
                'DELETE',
                nuage_staticroute.delete_resource(
                    static_route['nuage_static_route_id']), '')

    def get_nuage_static_route(self, params):
        req_params = {
            'address': params['address'],
            'nexthop': params['nexthop'],
            'domain_id': params['nuage_domain_id']
        }

        static_route = nuagelib.NuageStaticRoute(create_params=req_params)
        nuage_extra_headers = static_route.extra_headers_get()

        response = self.restproxy.rest_call(
            'GET', static_route.get_resources_of_domain(), '',
            extra_headers=nuage_extra_headers)

        if not static_route.validate(response):
            raise restproxy.RESTProxyError(static_route.error_msg)

        if len(response[3]) > 0:
            ret = {
                'nuage_zone_id': response[3][0]['ID'],
                'nuage_static_route_id': response[3][0]['ID'],
                'rd': response[3][0]['routeDistinguisher']
            }

            return ret

    def create_nuage_staticroute(self, params):
        req_params = {
            'domain_id': params['nuage_domain_id'],
            'router_id': params['neutron_rtr_id'],
            'net': params['net'],
            'nexthop': params['nexthop']
        }
        nuage_staticroute = nuagelib.NuageStaticRoute(create_params=req_params)
        response = self.restproxy.rest_call(
            'POST', nuage_staticroute.post_resource(),
            nuage_staticroute.post_data())
        if not nuage_staticroute.validate(response):
            code = nuage_staticroute.get_error_code(response)
            raise restproxy.RESTProxyError(nuage_staticroute.error_msg, code)
        return nuage_staticroute.get_staticrouteid(response)

    def _attach_nuage_group_to_zone(self, nuage_groupid, nuage_zoneid,
                                    neutron_tenant_id):
        nuage_permission = nuagelib.NuagePermission()
        resp = self.restproxy.rest_call(
            'POST',
            nuage_permission.post_resource_by_parent_id('zones', nuage_zoneid),
            nuage_permission.perm_create_data(
                nuage_groupid,
                constants.NUAGE_PERMISSION_USE,
                neutron_tenant_id))
        if not nuage_permission.validate(resp):
            if (nuage_permission.get_error_code(resp) !=
                    constants.CONFLICT_ERR_CODE):
                raise restproxy.RESTProxyError(
                    nuage_permission.error_msg)

    def get_zone_by_domainid(self, domain_id):
        nuage_l3_domain = nuagelib.NuageL3Domain({'domain_id': domain_id})
        response = self.restproxy.rest_call(
            'GET', nuage_l3_domain.get_all_zones(), '')
        if not nuage_l3_domain.validate(response):
            raise restproxy.RESTProxyError(
                nuage_l3_domain.error_msg,
                nuage_l3_domain.get_error_code(response))
        res = []
        for zone in nuage_l3_domain.get_response_objlist(response):
            np_dict = dict()
            np_dict['zone_name'] = zone['name']
            np_dict['zone_id'] = zone['ID']
            res.append(np_dict)
        return res

    def get_zone_by_routerid(self, neutron_router_id, shared=False):
        nuage_rtr_id = helper.get_l3domid_by_router_id(
            self.restproxy, neutron_router_id)
        l3dom_tmplt_id = helper.get_l3dom_template_id_by_dom_id(
            self.restproxy, nuage_rtr_id)

        req_params = {
            'domain_id': nuage_rtr_id
        }
        nuage_l3_domain = nuagelib.NuageL3Domain(create_params=req_params)

        if shared:
            zone_name = constants.DEF_NUAGE_ZONE_PREFIX + '-pub-' + \
                l3dom_tmplt_id
        else:
            zone_name = constants.DEF_NUAGE_ZONE_PREFIX + '-' + l3dom_tmplt_id

        nuage_extra_headers = nuage_l3_domain.extra_headers_get_name(zone_name)
        response = self.restproxy.rest_call(
            'GET', nuage_l3_domain.get_all_zones(), '',
            extra_headers=nuage_extra_headers)
        if not nuage_l3_domain.validate(response):
            raise restproxy.RESTProxyError(nuage_l3_domain.error_msg)
        if shared:
            if response[constants.VSD_RESP_OBJ]:
                return response[3][0]
            else:
                # TODO(Divya): try seems to be not required here
                try:
                    nuage_extra_headers = (
                        nuage_l3_domain.extra_headers_get_name(
                            TEMPLATE_SHARED_ZONE))
                    shared_zone = self.restproxy.rest_call(
                        'GET', nuage_l3_domain.get_all_zones(), '',
                        extra_headers=nuage_extra_headers)
                    if not nuage_l3_domain.validate(shared_zone):
                        raise restproxy.RESTProxyError(
                            nuage_l3_domain.error_msg)
                    if shared_zone[VSD_RESP_OBJ]:
                        return shared_zone[VSD_RESP_OBJ][0]
                except Exception:
                    return None
        else:
            if response[constants.VSD_RESP_OBJ]:
                return response[3][0]
            else:
                # This is needed for add_router_interface to a router created
                # with nuage-router-template parameter
                # return None when called from router_delete
                # TODO(Divya): try seems to be not required here
                try:
                    nuage_extra_headers = (
                        nuage_l3_domain.extra_headers_get_name(
                            TEMPLATE_ISOLATED_ZONE))
                    isolated_zone = self.restproxy.rest_call(
                        'GET', nuage_l3_domain.get_all_zones(), '',
                        extra_headers=nuage_extra_headers)
                    if not nuage_l3_domain.validate(isolated_zone):
                        raise restproxy.RESTProxyError(
                            nuage_l3_domain.error_msg)
                    if isolated_zone[VSD_RESP_OBJ]:
                        return isolated_zone[VSD_RESP_OBJ][0]
                except Exception:
                    return None

        return None

    def _get_nuage_static_routes_by_router_id(self, neutron_router_id):
        domain_id = helper.get_l3domid_by_router_id(self.restproxy,
                                                    neutron_router_id)
        req_params = {
            'domain_id': domain_id
        }
        nuage_route = nuagelib.NuageStaticRoute(create_params=req_params)
        response = self.restproxy.rest_call(
            'GET', nuage_route.post_resource(), '', '')

        if not nuage_route.validate(response):
            raise restproxy.RESTProxyError(nuage_route.error_msg)

        return response[3]

    def confirm_router_interface_not_in_use(self, neutron_router_id,
                                            neutron_subnet):
        nuage_routes = self._get_nuage_static_routes_by_router_id(
            neutron_router_id)
        for route in nuage_routes:
            if netaddr.all_matching_cidrs(route['nextHopIp'],
                                          [neutron_subnet['cidr']]):
                msg = ("router interface for subnet %s is required by one or"
                       " more routes") % neutron_subnet['name']
                raise restproxy.RESTProxyError(msg)

    def create_nuage_floatingip(self, params):
        req_params = {
            'domain_id': params['nuage_rtr_id'],
            'shared_netid': params['nuage_fippool_id'],
            'address': params['neutron_fip_ip'],
            'externalID': get_vsd_external_id(params['neutron_fip_id'])
        }
        nuage_fip = nuagelib.NuageFloatingIP(create_params=req_params)
        response = self.restproxy.rest_call('POST', nuage_fip.post_resource(),
                                            nuage_fip.post_data())
        if not nuage_fip.validate(response):
            code = nuage_fip.get_error_code(response)
            raise restproxy.RESTProxyError(nuage_fip.error_msg, code)
        return nuage_fip.get_fip_id(response)

    def get_nuage_floatingip(self, id, required=False, **filters):
        floatingip = nuagelib.NuageFloatingIP()
        floatingips = self.restproxy.get(
            floatingip.get_resource_by_id(id),
            extra_headers=floatingip.extra_header_filter(**filters),
            required=required)
        if floatingips:
            return floatingips[0]

    def get_nuage_floatingips(self, required=False, **filters):
        floatingip = nuagelib.NuageFloatingIP()
        return self.restproxy.get(
            floatingip.get_resource(),
            extra_headers=floatingip.extra_header_filter(**filters),
            required=required)

    def get_child_floatingips(self, parent_resource, parent_id,
                              required=False, **filters):
        floatingip = nuagelib.NuageFloatingIP()
        return self.restproxy.get(
            floatingip.get_child_resource(parent_resource, parent_id),
            extra_headers=floatingip.extra_header_filter(**filters),
            required=required)

    def delete_nuage_floatingip(self, id):
        nuagefip = nuagelib.NuageFloatingIP()
        resp = self.restproxy.rest_call('DELETE', nuagefip.delete_resource(id),
                                        '')
        if not nuagefip.validate(resp):
            code = nuagefip.get_error_code(resp)
            raise restproxy.RESTProxyError(nuagefip.error_msg,
                                           error_code=code)

    def update_vport_floatingip(self, vport_id, floatingip_id):
        floatingip = nuagelib.NuageFloatingIP()
        self.restproxy.put(
            floatingip.get_child_resource(nuagelib.NuageVPort.resource,
                                          vport_id),
            floatingip_id)

    def validate_port_create_redirect_target(self, params):
        nuage_subnet_id = params.get('nuage_subnet_id')
        if params.get('parent_type') == 'domain':
            nuage_domain_id = params.get('parent')
            nuagel3dom = nuagelib.NuageL3Domain()
            l3dom_subnets = self.restproxy.rest_call(
                'GET',
                nuagel3dom.get_domain_subnets(nuage_domain_id), '')
            if not nuagel3dom.validate(l3dom_subnets):
                raise self.restproxy.RESTProxyError(nuagel3dom.error_msg)

            for subnet in l3dom_subnets[3]:
                if subnet['ID'] == nuage_subnet_id:
                    return True
        elif params.get('parent_type') == constants.L2DOMAIN:
            nuage_l2domain_id = params.get('parent')
            if nuage_l2domain_id == nuage_subnet_id:
                return True
        return False

    def create_nuage_fip_for_vpnaas(self, params):
        req_params = {
            'domain_id': params['nuage_rtr_id'],
            'shared_netid': params['nuage_fippool_id'],
            'externalID': params['vpn_id']
        }
        nuage_fip = nuagelib.NuageFloatingIP(create_params=req_params)
        response = self.restproxy.rest_call('POST', nuage_fip.post_resource(),
                                            nuage_fip.post_fip_data())
        if not nuage_fip.validate(response):
            code = nuage_fip.get_error_code(response)
            raise restproxy.RESTProxyError(nuage_fip.error_msg, code)
        return response[3][0]


class NuageDomainSubnet(object):
    def __init__(self, restproxy_serv, policygroups):
        self.restproxy = restproxy_serv
        self.policygroups = policygroups

    def get_domain_subnet_by_id(self, nuage_id):
        nuagesubnet = nuagelib.NuageSubnet()
        return self.restproxy.get(nuagesubnet.get_resource(nuage_id),
                                  required=True)[0]

    def get_domain_subnet_by_zone_id(self, zone_id):
        subnet = nuagelib.NuageSubnet({'zone': zone_id})
        return self.restproxy.get(subnet.get_all_resources_in_zone())

    def create_domain_subnet(self, vsd_zone, os_subnet, pnet_binding):
        req_params = {
            'name': os_subnet['id'],
            'net': netaddr.IPNetwork(os_subnet['cidr']),
            'zone': vsd_zone['ID'],
            'gateway': os_subnet['gateway_ip'],
            'externalID': get_vsd_external_id(os_subnet['id'])
        }
        extra_params = {'description': os_subnet.get('name'),
                        'entityState': 'UNDER_CONSTRUCTION'}
        nuagel3domsub = nuagelib.NuageSubnet(create_params=req_params,
                                             extra_params=extra_params)
        vsd_subnet = self.restproxy.post(nuagel3domsub.post_resource(),
                                         nuagel3domsub.post_data())[0]

        nuagedhcpoptions = dhcpoptions.NuageDhcpOptions(self.restproxy)
        nuagedhcpoptions.create_nuage_dhcp(
            os_subnet,
            parent_id=vsd_subnet['ID'],
            network_type=constants.NETWORK_TYPE_L3)

        if pnet_binding:
            # Get netpart id needed in process_provider_network to check the
            # gateway port enterprise permissions
            req_params = {'domain_id': vsd_zone['parentID']}
            nuage_l3domain = nuagelib.NuageL3Domain(create_params=req_params)
            domain = self.restproxy.get(nuage_l3domain.get_resource())[0]
            np_id = helper.get_l3domain_np_id(self.restproxy, domain['ID'])

            pnet_params = {
                'pnet_binding': pnet_binding,
                'nuage_subnet_id': vsd_subnet['ID'],
                'netpart_id': np_id,
                'neutron_subnet_id': os_subnet['id']
            }
            pnet_helper.process_provider_network(self.restproxy,
                                                 self.policygroups,
                                                 pnet_params)
        return vsd_subnet

    def delete_domain_subnet(self, nuage_subn_id, neutron_subn_id,
                             pnet_binding):
        nuagel3domsub = nuagelib.NuageSubnet()
        if pnet_binding:
            pnet_helper.delete_resources_created_for_domainsubnet_providernet(
                self.restproxy, self.policygroups, nuage_subn_id,
                neutron_subn_id)

        # Delete domain_subnet
        self.restproxy.rest_call('DELETE',
                                 nuagel3domsub.delete_resource(nuage_subn_id),
                                 '')

    def validate_create_domain_subnet(self, neutron_subn, nuage_subnet_id,
                                      nuage_rtr_id):
        net_cidr = netaddr.IPNetwork(neutron_subn['cidr'])
        net_ip = net_cidr.ip

        nuagel3dom = nuagelib.NuageL3Domain()
        nuagel3domsub = self.restproxy.rest_call(
            'GET',
            nuagel3dom.get_domain_subnets(nuage_rtr_id), '',
            nuagel3dom.extra_headers_get_address(net_ip))

        if not nuagel3dom.validate(nuagel3domsub):
            raise self.restproxy.RESTProxyError(nuagel3dom.error_msg)

        if nuagel3domsub[3]:
            msg = ("Cidr %s of subnet %s overlaps with another subnet in the "
                   "VSD" % (net_cidr, nuage_subnet_id))
            raise restproxy.RESTProxyError(msg)
        return True

    def move_to_l2(self, subnet_id, l2domain_id):
        url = nuagelib.Job.post_url('subnets', subnet_id)
        try:
            self.restproxy.post(url, {
                'command': 'DETACH',
                'parameters': {'destinationL2DomainID': l2domain_id}
            })
        except restproxy.ResourceNotFoundException:
            pass
