export class ApiRoutes {
    private static readonly BASE_URL = 'http://localhost:8000/api/v1';

    public static Login = () => `${this.BASE_URL}/public/admins/login`;
    public static AdminSessions = () => `${this.BASE_URL}/private/admins/seances`;

    private static readonly TEMPLATES_BASE = '/private/templates';
    public static AllTemplates = () => `${this.BASE_URL}${this.TEMPLATES_BASE}/all`;
    public static Template = () => `${this.BASE_URL}${this.TEMPLATES_BASE}/by_id`;
    public static CreateTemplate = () => `${this.BASE_URL}${this.TEMPLATES_BASE}/add`;
    public static UpdateTemplate = () => `${this.BASE_URL}${this.TEMPLATES_BASE}/update`;
    public static DeleteTemplate = (id: number) => `${this.BASE_URL}${this.TEMPLATES_BASE}/delete?tmp_id=${id}`;

    private static readonly PROTOCOLS_BASE = '/private/protocols';
    public static AllProtocols = () => `${this.BASE_URL}${this.PROTOCOLS_BASE}/all`;
    public static Protocol = (id: number) => `${this.BASE_URL}${this.PROTOCOLS_BASE}/${id}`;
    public static CreateProtocol = () => `${this.BASE_URL}${this.PROTOCOLS_BASE}/create`;
    public static DeleteProtocol = (id: number) => `${this.BASE_URL}${this.PROTOCOLS_BASE}/delete/${id}`;
}
