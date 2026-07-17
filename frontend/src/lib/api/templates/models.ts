export class Template {
    id: number;
    title: string;
    url_tmp?: string;
    status: number;
    is_accepted: boolean;
    proto_python_lib?: string;

    public constructor(id: number, title: string, url_tmp: string, status: number, is_accepted: boolean, proto_python_lib: string) {
        this.id = id;
        this.title = title;
        this.url_tmp = url_tmp;
        this.status = status;
        this.is_accepted = is_accepted;
        this.proto_python_lib = proto_python_lib;
    }

    public statusString(): string {
        switch (this.status) {
            case 1:
                return "System";
            case 2:
                return "User";
            default:
                return "undefined"
        }
    }
}

export class PostTemplateForm {
    title: string

    public constructor(title: string) {
        this.title = title;
    }
}

export class UpdateTemplateForm {
    tmp_id: number
    title: string

    public constructor(tmp_id: number, title: string) {
        this.tmp_id = tmp_id;
        this.title = title;
    }
}
