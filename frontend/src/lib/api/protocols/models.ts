export class Protocol {
    proto_id: number;
    name: string;
    created_at: Date;
    tmp_id: number;
    tmp_name: string;

    constructor(proto_id: number, name: string, created_at: Date, tmp_id: number, tmp_name: string) {
        this.proto_id = proto_id;
        this.name = name;
        this.created_at = created_at;
        this.tmp_id = tmp_id;
        this.tmp_name = tmp_name;
    }
}

export class PostProtocolForm {
    name: string;
    tmp_id: number;

    constructor(name: string, tmp_id: number) {
        this.name = name;
        this.tmp_id = tmp_id;
    }
}
