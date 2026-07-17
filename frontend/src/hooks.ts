import { Template } from '$lib/api/templates/models';
import { Protocol } from '$lib/api/protocols/models';
import type { Transport } from '@sveltejs/kit';

export const transport: Transport = {
    Template: {
        encode: (value) => value instanceof Template && [value.id, value.title, value.url_tmp ?? '', value.status, value.is_accepted, value.proto_python_lib ?? ''],
        decode: ([id, title, url_tmp, status, is_accepted, proto_python_lib]) => new Template(id, title, url_tmp, status, is_accepted, proto_python_lib),
    },
    Protocol: {
        encode: (value) => value instanceof Protocol && [value.proto_id, value.name, value.created_at, value.tmp_id, value.tmp_name],
        decode: ([proto_id, name, created_at, tmp_id, tmp_name]) => new Protocol(proto_id, name, created_at, tmp_id, tmp_name),
    },
};
