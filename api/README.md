# Documentation of nova API extension built by Platform9 #

## Data format ##
Although openstack API framework supports JSON and XML formats for data
exchange, this document is limited to json examples.

## API ##

### GET nova/v2/project_id/os-networks ###

Returns a list of networks with their access information.

Example:

```
{
   "network":
   {

   ....

   "range_start": "192.168.1.10",
   "range_end": "192.168.1.200",

   ....

   "project_access_pf9": ['20d398e8e3d849c581686a3bb44a1e7d',
                          'e246889348ff45e5bf654cf52cdfcbcd',
                          '6809736774634cb4b7351bd0a63fdaab']
   },
   "network":
   {

   ....


   "range_start": "192.168.1.10",
   "range_end": "192.168.1.200",

   ....

   "project_access_pf9": ['6809736774634cb4b7351bd0a63fdaab']
   }
}
```

### GET nova/v2/project_id/os-networks/network_id ###

Returns a dictionary of project ids with which this network is shared.

Example:

```
{
   "network":
   {

   ....

   "project_access_pf9": ['20d398e8e3d849c581686a3bb44a1e7d',
                          'e246889348ff45e5bf654cf52cdfcbcd',
                          '6809736774634cb4b7351bd0a63fdaab']
   }
}
```


### POST nova/v2/project_id/os-networks/network_id/action ###

Currently supported actions are:
addProject: Add project to network access list
removeProject: Remove project from network access list

Requires HTTP body to describe action and associated project ID.
Example:

```
{
    'addProject':
    { 'project_id': '6809736774634cb4b7351bd0a63fdaab'}
}
```

```
{
    'removeProject':
    { 'project_id': '6809736774634cb4b7351bd0a63fdaab'}
}
```

Returns: HTTP code describing success or failure.
